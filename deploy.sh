#!/usr/bin/env bash
# Production deployment for THIS project only (Compose project "whatsapp-automation-bot").
#
# It deploys one exact, already validated commit. It never uses `docker compose down`, never touches
# volumes, never uses a global Docker prune and never touches other applications on the server.
#
# Usage on the server
#   bash deploy.sh --from-ssh      forced SSH command: reads the commit SHA the workflow sent
#   bash deploy.sh <40-hex sha>    manual deployment of that commit (its message must contain [prod])
#   bash deploy.sh --check-only    pre-flight checks only: builds and starts nothing
#   bash deploy.sh --help
#
# Forced command for the workflow's SSH key (authorized_keys, ONE line; see README "CI/CD"):
#   command="cd /var/www/whatsapp-automation-bot && bash deploy.sh --from-ssh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... wa-actions-deploy
# sshd puts whatever the client asked to run into SSH_ORIGINAL_COMMAND. This script accepts it only if it
# is exactly one 40-character hexadecimal commit SHA; anything else is rejected before any action.
#
# Stages: lock -> exact SHA checkout -> pre-flight -> change detection -> preserve current images ->
#         build changed services -> backup + migrate (only if there are pending migrations) ->
#         backend deploy + verify -> frontend deploy + verify -> end-to-end check -> record SHA -> cleanup.
# Any failure after a container was replaced triggers an automatic image rollback of that service.
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"
for lib in common detect migrations docker preflight backup; do
  # shellcheck source=/dev/null
  . "$REPO_DIR/scripts/lib/$lib.sh"
done
# Deployments always build and run `latest`; never inherit a tag override from the caller.
unset BACKEND_IMAGE_TAG FRONTEND_IMAGE_TAG

GIT_DIR_ABS="$(git rev-parse --absolute-git-dir)"
STATE_DIR="$GIT_DIR_ABS/deploy-state" # inside .git: never shows up as an untracked file

# ---- state of the current run (used by the rollback handler) ----------------------------------------
SHA=""
MSG=""
BUILT_SERVICES=""     # images that were built (the :latest tag may have moved)
DEPLOYED_SERVICES=""  # services whose container was replaced
MIGRATED=no           # set to yes just before migrations run
ROLLBACK_ARMED=no
DEPLOY_OK=no

usage() {
  cat <<'EOF'
Usage:
  bash deploy.sh --from-ssh        forced SSH command (reads the SHA from SSH_ORIGINAL_COMMAND)
  bash deploy.sh <40-hex-sha>      deploy that commit (its message must contain [prod])
  bash deploy.sh --check-only      run the pre-flight checks only
EOF
}

read_last_deployed() {
  local f="$STATE_DIR/last_deployed_sha" v=""
  if [ -f "$f" ]; then v=$(tr -d '[:space:]' <"$f"); fi
  if is_sha "$v"; then printf '%s' "$v"; fi
  return 0
}

record_success() { # sha services migrated
  mkdir -p "$STATE_DIR"
  printf '%s\n' "$1" >"$STATE_DIR/last_deployed_sha.tmp"
  mv "$STATE_DIR/last_deployed_sha.tmp" "$STATE_DIR/last_deployed_sha"
  printf '%s %s SUCCESS services=[%s] migrated=%s\n' "$(date -u +%FT%TZ)" "$1" "$2" "$3" >>"$STATE_DIR/history.log"
}

# ---- stage 1: lock, validate, check out the exact commit, hand over ------------------------------------
mode_ssh() {
  local cmd="${SSH_ORIGINAL_COMMAND-}"
  is_sha "$cmd" || die "SSH command rejected: expected exactly one 40-character hexadecimal commit SHA. Nothing was changed."
  mode_bootstrap "$cmd"
}

mode_bootstrap() {
  local sha="$1" msg
  require_sha "$sha"
  command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 || die "docker compose is not available"
  acquire_lock "$GIT_DIR_ABS/deploy.lock"

  step "1. Check out the validated commit $sha"
  [ -z "$(git status --porcelain)" ] || die "the working tree has uncommitted or untracked changes; refusing to overwrite unknown changes. Nothing was changed."
  ok "working tree is clean"
  git fetch --quiet origin main || die "git fetch failed. Nothing was changed."
  git cat-file -e "${sha}^{commit}" 2>/dev/null || die "commit $sha is not available from origin"
  git merge-base --is-ancestor "$sha" origin/main || die "commit $sha is not part of origin/main"
  msg=$(git log -1 --format=%B "$sha")
  gate_prod "$msg" || die "the commit message does not contain [prod]; refusing to deploy"
  ok "commit is on main and carries [prod]"
  git checkout --quiet --detach "$sha" || die "git checkout failed. Nothing was deployed."
  [ "$(git rev-parse HEAD)" = "$sha" ] || die "the checked-out commit does not match the requested SHA"
  ok "checked out exactly $sha"

  # Hand over to the freshly checked-out copy of this script, so every deployment runs the deployment
  # logic of the commit being deployed. exec keeps the lock (file descriptor 9).
  exec bash "$REPO_DIR/deploy.sh" --run "$sha"
}

mode_check() {
  preflight
  echo
  echo "All checks passed (--check-only: nothing was built or started)."
}

# ---- stage 2: the deployment itself --------------------------------------------------------------------
mode_run() {
  local sha="${1-}"
  require_sha "$sha"
  [ "$(git rev-parse HEAD)" = "$sha" ] || die "HEAD is not $sha: --run must follow a checkout of the validated commit"
  if ! { : >&9; } 2>/dev/null; then acquire_lock "$GIT_DIR_ABS/deploy.lock"; fi # started by hand without the bootstrap
  mkdir -p "$STATE_DIR"
  SHA="$sha"
  MSG=$(git log -1 --format=%B "$sha")
  gate_prod "$MSG" || die "the commit message does not contain [prod]"

  preflight

  step "3. What changed since the last successful deployment"
  local prev paths plan BUILD_BACKEND BUILD_FRONTEND
  prev=$(read_last_deployed)
  if [ -z "$prev" ]; then
    info "no previously deployed commit is recorded: first deployment under this system, rebuilding both services"
    plan=$(detect_plan_all)
  elif ! git cat-file -e "${prev}^{commit}" 2>/dev/null; then
    warn "the previously deployed commit ${prev:0:12} is not in this repository; rebuilding both services to be safe"
    plan=$(detect_plan_all)
  else
    paths=$(git diff --name-only --no-renames "$prev" "$sha")
    plan=$(printf '%s\n' "$paths" | detect_plan)
    info "previous deployed commit: ${prev:0:12}"
  fi
  BUILD_BACKEND=$(plan_get build_backend "$plan")
  BUILD_FRONTEND=$(plan_get build_frontend "$plan")
  info "change categories: $(plan_get categories "$plan")"
  info "decision: $(plan_get summary "$plan") | backend rebuild: $BUILD_BACKEND | frontend rebuild: $BUILD_FRONTEND"

  if [ "$BUILD_BACKEND" = no ] && [ "$BUILD_FRONTEND" = no ]; then
    step "No container rebuild or restart is needed"
    record_success "$sha" "none" "no"
    ok "recorded $sha as the deployed commit (no image was built, no container was touched)"
    echo; echo "DEPLOY RESULT: SUCCESS commit=$sha services=none"
    return 0
  fi

  local services=""
  [ "$BUILD_BACKEND" = yes ] && services="backend"
  [ "$BUILD_FRONTEND" = yes ] && services="$services frontend"
  services="${services# }"

  ROLLBACK_ARMED=yes
  trap 'on_exit $?' EXIT
  trap 'exit 143' HUP TERM INT PIPE # an interrupted deployment ends in the rollback handler, not half-way

  step "4. Preserve the running images and build only the changed services: $services"
  local svc
  for svc in $services; do
    BUILT_SERVICES="$BUILT_SERVICES $svc"
    preserve_previous "$svc" || die "could not preserve the current $svc image; nothing was deployed"
    build_service "$svc" "$sha" || die "the $svc image failed to build; $svc was not deployed"
    ok "$svc built and tagged $(repo_of "$svc"):$sha"
  done

  if in_list backend "$services"; then stage_migrations; fi

  for svc in $services; do stage_deploy "$svc"; done

  step "Final end-to-end verification"
  verify_integration || die "the final integration check failed"

  record_success "$sha" "$services" "$MIGRATED"
  DEPLOY_OK=yes
  step "Cleanup of old images of this project"
  cleanup_images "$sha"
  echo
  echo "DEPLOY RESULT: SUCCESS commit=$sha services=[$services] migrated=$MIGRATED"
}

stage_migrations() {
  step "5. Database migrations"
  local plan files_text risky approved=no
  local -a files=()

  # migration files must be committed: the models must not need a migration that is not in Git
  dc run --rm --no-deps -T backend python manage.py makemigrations --check --dry-run >/dev/null \
    || die "the models have changes without a committed migration file (makemigrations --check failed). Commit the migration and push again. Nothing was changed."
  ok "no uncommitted model changes"

  plan=$(dc run --rm --no-deps -T backend python manage.py migrate --plan 2>&1) || die "could not compute the migration plan. Nothing was changed."
  if printf '%s\n' "$plan" | grep -q 'No planned migration operations'; then
    ok "no pending migrations: no backup and no migration needed"
    return 0
  fi
  info "pending migrations (plan):"
  printf '%s\n' "$plan" | sed 's/^/        /'

  files_text=$(printf '%s\n' "$plan" | plan_migration_files "$REPO_DIR")
  if [ -n "$files_text" ]; then
    mapfile -t files <<<"$files_text"
    if risky=$(scan_destructive "${files[@]}"); then
      if gate_migrate_ok "$MSG"; then
        approved=yes
        warn "potentially destructive or data-changing migration operations, APPROVED by [migrate-ok]:"
        printf '%s\n' "$risky" | sed 's/^/        /' >&2
      else
        printf '%s\n' "$risky" | sed 's/^/        /' >&2
        die "potentially destructive or data-changing migration operations were found (listed above) and the commit message does not contain [migrate-ok]. NOTHING was changed: no backup, no migration, no container touched. Review the migration, then push again with [prod] [migrate-ok] in the commit message."
      fi
    fi
  fi
  [ "$approved" = yes ] || ok "no destructive operations in the pending migrations"

  info "backing up the database before migrating"
  backup_database "$SHA" || die "the database backup failed, so the migrations were NOT applied. Nothing else was changed."
  ok "backup written to the volume and to $HOST_BACKUP_DIR and verified"

  MIGRATED=yes # from here on the database may differ from what the previous image expects
  dc run --rm --no-deps -T backend python manage.py migrate --noinput \
    || die "the migration failed. The backup is kept in $HOST_BACKUP_DIR; the running application was not touched. Do NOT restore automatically: inspect the error first."
  plan=$(dc run --rm --no-deps -T backend python manage.py migrate --plan 2>&1) || die "could not re-check the migration plan"
  printf '%s\n' "$plan" | grep -q 'No planned migration operations' || die "migrations are still pending after migrate"
  ok "migrations applied exactly once and verified"
}

stage_deploy() { # service
  local svc="$1" since
  since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  step "Deploy $svc"
  DEPLOYED_SERVICES="$DEPLOYED_SERVICES $svc"
  dc up -d --no-deps "$svc" || die "could not start the new $svc container"
  wait_healthy "$svc" 150 || die "$svc did not become healthy"
  ok "$svc container reports healthy"
  case "$svc" in
    backend) verify_backend "$since" || die "backend verification failed" ;;
    frontend) verify_frontend || die "frontend verification failed" ;;
  esac
}

# ---- failure handling ------------------------------------------------------------------------------------
on_exit() {
  local rc="$1" svc failed=no
  trap - EXIT
  trap '' PIPE HUP
  set +e
  if [ "$DEPLOY_OK" = yes ] && [ "$rc" -eq 0 ]; then exit 0; fi
  [ "$rc" -ne 0 ] || rc=1
  if [ "$ROLLBACK_ARMED" != yes ]; then exit "$rc"; fi

  step "ROLLBACK: the deployment did not complete"
  # shellcheck disable=SC2086 # intentional word splitting of the service lists
  capture_failure_logs "$STATE_DIR/failures" "${SHA:-unknown}" $BUILT_SERVICES

  for svc in frontend backend; do # newest-dependent first
    if in_list "$svc" "$DEPLOYED_SERVICES"; then
      if rollback_service "$svc"; then
        ok "$svc: previous image restored and healthy"
      else
        warn "$svc: the previous image could not be restored to a healthy state"
        failed=yes
      fi
    elif in_list "$svc" "$BUILT_SERVICES"; then
      restore_latest_tag "$svc"
      info "$svc: was built but never started; its latest tag was moved back, the running container was not touched"
    fi
  done

  if [ "$MIGRATED" = yes ]; then
    warn "database migrations were applied before this failure. They were NOT reversed."
    warn "Backups: $HOST_BACKUP_DIR (and /data/backups in the volume). If the restored backend cannot run against the migrated database, restore a backup manually (see scripts/lib/backup.sh)."
  fi
  mkdir -p "$STATE_DIR"
  printf '%s %s FAILED rolled_back=[%s] rollback_failed=%s migrated=%s\n' "$(date -u +%FT%TZ)" "${SHA:-unknown}" "$DEPLOYED_SERVICES" "$failed" "$MIGRATED" >>"$STATE_DIR/history.log"
  echo
  if [ "$failed" = yes ]; then
    echo "DEPLOY RESULT: FAILED and the automatic rollback was NOT fully successful: manual attention required (commit=${SHA:-unknown})"
  else
    echo "DEPLOY RESULT: FAILED, previous version restored (commit=${SHA:-unknown})"
  fi
  exit "$rc"
}

main() {
  case "${1-}" in
    --from-ssh) mode_ssh ;;
    --check-only) mode_check ;;
    --run) shift; mode_run "${1-}" ;;
    -h|--help) usage ;;
    "")
      # Transition: the old forced command ("git pull && bash deploy.sh") passes no argument; the
      # workflow's SHA then arrives in SSH_ORIGINAL_COMMAND, so it is handled exactly like --from-ssh.
      if [ -n "${SSH_ORIGINAL_COMMAND-}" ]; then mode_ssh; else usage >&2; return 2; fi
      ;;
    -*) usage >&2; return 2 ;;
    *) mode_bootstrap "$1" ;;
  esac
}

# The guard allows the test script to source this file. The whole compound command is read before
# it runs, so replacing this file during a deployment (git checkout) cannot confuse the running shell.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
  exit $?
fi
