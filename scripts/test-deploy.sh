#!/usr/bin/env bash
# Tests for the deployment logic. Needs only bash, git and (for the lock tests) flock.
# No Docker daemon and no production access: docker / docker compose are replaced by fakes, and every
# scenario runs against throw-away Git repositories in a temporary directory.
#
#   bash scripts/test-deploy.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT

PASS=0; FAIL=0; SKIP=0; OUT=""; RC=0

pass() { PASS=$((PASS + 1)); printf '  PASS  %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [ -z "${2-}" ] || printf '%s\n' "$2" | sed 's/^/        | /'; }
skip() { SKIP=$((SKIP + 1)); printf '  SKIP  %s\n' "$1"; }
section() { printf '\n--- %s\n' "$1"; }

run_sub() { OUT=$( ( "$@" ) 2>&1 ); RC=$?; }                 # run a function in a subshell, capture output + status
expect_ok()   { if [ "$RC" -eq 0 ]; then pass "$1"; else fail "$1 (exit $RC)" "$OUT"; fi; }
expect_fail() { if [ "$RC" -ne 0 ]; then pass "$1"; else fail "$1 (expected a failure, got exit 0)" "$OUT"; fi; }
expect_has()   { if grep -qF -- "$2" <<<"$OUT"; then pass "$1"; else fail "$1: output does not contain: $2" "$OUT"; fi; }
expect_lacks() { if grep -qF -- "$2" <<<"$OUT"; then fail "$1: output must not contain: $2" "$OUT"; else pass "$1"; fi; }
expect_eq() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1: expected '$3' but got '$2'"; fi; }
calls_has()   { if grep -qE -- "$2" "$CALLS"; then pass "$1"; else fail "$1: calls do not contain: $2" "$(cat "$CALLS")"; fi; }
calls_lacks() { if grep -qE -- "$2" "$CALLS"; then fail "$1: calls must not contain: $2" "$(cat "$CALLS")"; else pass "$1"; fi; }

load_libs() { local l; for l in common detect migrations docker preflight backup; do . "$ROOT/scripts/lib/$l.sh"; done; }
load_libs # functions only; die() is only ever called inside subshells below

# =============================================================================================
section "Commit SHA validation"
t_sha() { load_libs; is_sha "$1"; }
for good in 0123456789abcdef0123456789abcdef01234567 ffffffffffffffffffffffffffffffffffffffff; do
  run_sub t_sha "$good"; expect_ok "accepts $good"
done
for bad in "" abc 0123456789abcdef0123456789abcdef0123456 0123456789abcdef0123456789abcdef012345678 \
           0123456789ABCDEF0123456789ABCDEF01234567 "0123456789abcdef0123456789abcdef0123456g" \
           '$(touch /tmp/pwned-by-test)' '0123456789abcdef0123456789abcdef01234567; rm -rf /' ' 0123456789abcdef0123456789abcdef01234567'; do
  run_sub t_sha "$bad"; expect_fail "rejects '${bad:0:50}'"
done
[ ! -e /tmp/pwned-by-test ] && pass "a command-substitution SHA was never executed" || fail "a command inside the SHA was executed"

section "Commit message gates"
t_gate() { load_libs; "$@"; }
run_sub t_gate gate_prod "Improve webhook [prod]";            expect_ok   "[prod] present is accepted"
run_sub t_gate gate_prod "Improve webhook";                   expect_fail "missing [prod] is rejected"
run_sub t_gate gate_prod "Improve webhook prod";              expect_fail "'prod' without brackets is rejected"
run_sub t_gate gate_prod "Improve webhook [PROD]";            expect_fail "[PROD] (wrong case) is rejected"
run_sub t_gate gate_migrate_ok "x [prod] [migrate-ok]";       expect_ok   "[migrate-ok] present is accepted"
run_sub t_gate gate_migrate_ok "x [prod]";                    expect_fail "missing [migrate-ok] is rejected"

# =============================================================================================
section "Change detection"
plan_for() { load_libs; printf '%s\n' "$@" | detect_plan; }
check_plan() { # name backend frontend migrations paths...
  local name="$1" be="$2" fe="$3" mig="$4"; shift 4
  run_sub plan_for "$@"
  expect_eq "$name: backend=$be" "$(plan_get build_backend "$OUT")" "$be"
  expect_eq "$name: frontend=$fe" "$(plan_get build_frontend "$OUT")" "$fe"
  expect_eq "$name: migrations=$mig" "$(plan_get migrations "$OUT")" "$mig"
}
check_plan "backend source only"        yes no  no  backend/messaging/views.py backend/config/settings.py
check_plan "backend requirements"       yes no  no  backend/requirements.txt
check_plan "backend constraints"        yes no  no  backend/constraints.txt
check_plan "backend Dockerfile"         yes no  no  backend/Dockerfile
check_plan "backend migration"          yes no  yes backend/messaging/migrations/0006_x.py backend/messaging/models.py
check_plan "backend asset (media)"      yes no  no  backend/media/image.png
check_plan "frontend source only"       no  yes no  frontend/src/App.jsx frontend/public/sw.js
check_plan "frontend dependencies"      no  yes no  frontend/package-lock.json
check_plan "frontend nginx.conf"        no  yes no  frontend/nginx.conf
check_plan "frontend Dockerfile"        no  yes no  frontend/Dockerfile
check_plan "backend and frontend"       yes yes no  backend/messaging/views.py frontend/src/App.jsx
check_plan "compose file"               yes yes no  docker-compose.yml
check_plan "unknown file (conservative)" yes yes no Makefile
check_plan "docs + backend source"      yes no  no  README.md backend/messaging/views.py
check_plan "documentation only"         no  no  no  README.md backend/.env.example frontend/README.md
check_plan "backend tests only"         no  no  no  backend/messaging/test_runs.py backend/messaging/tests.py
check_plan "deployment scripts only"    no  no  no  deploy.sh scripts/lib/docker.sh
check_plan "CI workflow only"           no  no  no  .github/workflows/deploy.yml
check_plan "lint config only"           no  no  no  frontend/.oxlintrc.json
run_sub plan_for README.md;   expect_has "documentation-only summary" "documentation only"
run_sub plan_for deploy.sh;   expect_has "scripts-only summary" "no service-affecting changes"
run_sub plan_for;             expect_has "no changes summary" "no changes since the last deployed commit"
t_all() { load_libs; detect_plan_all; }
run_sub t_all; expect_eq "first deployment rebuilds backend" "$(plan_get build_backend "$OUT")" yes
expect_eq "first deployment rebuilds frontend" "$(plan_get build_frontend "$OUT")" yes

# =============================================================================================
section "Migration safety scan"
M="$W/mig"; mkdir -p "$M/backend/messaging/migrations"
mkmig() { printf 'from django.db import migrations\nclass Migration(migrations.Migration):\n    operations = [\n        %s\n    ]\n' "$2" > "$M/backend/messaging/migrations/$1.py"; }
mkmig 0002_benign   "migrations.CreateModel(name='X', fields=[]), migrations.AddField(model_name='x', name='y', field=None)"
mkmig 0003_remove   "migrations.RemoveField(model_name='x', name='y')"
mkmig 0004_delete   "migrations.DeleteModel(name='X')"
mkmig 0005_rename   "migrations.RenameModel(old_name='X', new_name='Y')"
mkmig 0006_alter    "migrations.AlterField(model_name='x', name='y', field=None)"
mkmig 0007_python   "migrations.RunPython(None)"
mkmig 0008_sql      "migrations.RunSQL('UPDATE x SET y = 1')"
t_scan() { load_libs; scan_destructive "$@"; }
run_sub t_scan "$M/backend/messaging/migrations/0002_benign.py"; expect_fail "additive migration (CreateModel/AddField) is not flagged"
for pair in 0003_remove:RemoveField 0004_delete:DeleteModel 0005_rename:RenameModel 0006_alter:AlterField 0007_python:RunPython 0008_sql:RunSQL; do
  run_sub t_scan "$M/backend/messaging/migrations/${pair%%:*}.py"
  expect_ok "flags ${pair##*:}"; expect_has "reports ${pair##*:}" "${pair##*:}"
done
PLAN_SAMPLE=$'Planned operations:\ncontenttypes.0001_initial\n    Create model ContentType\nauth.0001_initial\n    Create model Permission\nmessaging.0003_remove\n    Remove field y from x\nmessaging.0002_benign\n    Create model X'
t_planfiles() { load_libs; printf '%s\n' "$PLAN_SAMPLE" | plan_migration_files "$M"; }
run_sub t_planfiles
expect_has "plan parser finds the repository migration" "0003_remove.py"
expect_has "plan parser finds the second migration" "0002_benign.py"
expect_lacks "plan parser ignores Django's built-in apps" "contenttypes"

# =============================================================================================
section "Deployment lock"
if command -v flock >/dev/null 2>&1; then
  t_hold()  { load_libs; acquire_lock "$W/test.lock"; sleep 4; }
  t_try()   { load_libs; acquire_lock "$W/test.lock"; echo "lock acquired"; }
  ( t_hold ) & HOLDER=$!
  sleep 1
  run_sub t_try; expect_fail "a second deployment cannot start while one is running"; expect_has "clear message" "another deployment is already running"
  wait "$HOLDER" 2>/dev/null
  run_sub t_try; expect_ok "the lock is free again after the first deployment ended"
else
  skip "deployment lock tests (flock is not installed here; they run in the Linux container)"
fi

# =============================================================================================
section "Entry point: SSH command, SHA, [prod], clean tree (real deploy.sh, fake docker)"
mkdir -p "$W/bin"
cat >"$W/bin/docker" <<'EOF'
#!/bin/sh
echo "$@" >> "$FAKE_DOCKER_LOG"
[ "$1 $2" = "compose version" ] && echo "Docker Compose version fake"
exit 0
EOF
chmod +x "$W/bin/docker"

mk_origin_repo() {
  rm -rf "$W/origin.git" "$W/work"
  git init -q --bare -b main "$W/origin.git"
  git init -q -b main "$W/work"
  ( cd "$W/work" || exit 1
    git config user.email t@example.com; git config user.name tester; git config core.autocrlf false
    git remote add origin "$W/origin.git"
    mkdir -p scripts; cp "$ROOT/deploy.sh" .; cp -r "$ROOT/scripts/." scripts/
    git add -A; git commit -q -m "base"
    echo a >a.txt; git add -A; git commit -q -m "feature [prod]"
    echo b >b.txt; git add -A; git commit -q -m "docs [prod] [migrate-ok]"
    git push -q origin main 2>/dev/null
  )
}
mk_origin_repo
SHA_BASE=$(git -C "$W/work" rev-parse HEAD~2)
SHA_PROD=$(git -C "$W/work" rev-parse HEAD~1)
SHA_TIP=$(git -C "$W/work" rev-parse HEAD)
: >"$W/docker.log"
entry() { # ssh-command [args...]
  local cmd="$1"; shift
  ( cd "$W/work" && PATH="$W/bin:$PATH" FAKE_DOCKER_LOG="$W/docker.log" SSH_ORIGINAL_COMMAND="$cmd" bash deploy.sh "$@" )
}
no_build_calls() { ! grep -qE 'compose (build|up|run)' "$W/docker.log"; }

run_sub entry 'rm -rf /' --from-ssh;                          expect_fail "SSH: arbitrary command is rejected"; expect_has "SSH: reason shown" "expected exactly one 40-character"
run_sub entry 'abc123' --from-ssh;                            expect_fail "SSH: short SHA is rejected"
run_sub entry "$(echo "$SHA_PROD" | tr a-f A-F)" --from-ssh;  expect_fail "SSH: uppercase SHA is rejected"
run_sub entry "$SHA_PROD; id" --from-ssh;                     expect_fail "SSH: SHA with an appended command is rejected"
run_sub entry '' --from-ssh;                                  expect_fail "SSH: empty command is rejected"
run_sub entry 'rm -rf /';                                     expect_fail "legacy no-argument form also rejects a bad command"
run_sub entry '';                                             expect_fail "no argument and no SSH command prints usage"; expect_has "usage shown" "Usage:"
run_sub entry '' --help;                                      expect_ok "--help works"
no_build_calls && pass "nothing was built or started by any rejected request" || fail "docker build/up ran during a rejected request" "$(cat "$W/docker.log")"

run_sub entry "$SHA_BASE" --from-ssh;                         expect_fail "commit without [prod] is rejected"; expect_has "message names [prod]" "does not contain [prod]"
expect_eq "rejected request left the checkout on main" "$(git -C "$W/work" rev-parse --abbrev-ref HEAD)" main
run_sub entry 0000000000000000000000000000000000000000 --from-ssh; expect_fail "unknown commit is rejected"; expect_has "reason shown" "not available from origin"

( cd "$W/work" && git checkout -q -b side && echo s >s.txt && git add -A && git commit -q -m "side branch [prod]" && git checkout -q main )
SHA_SIDE=$(git -C "$W/work" rev-parse side)
run_sub entry "$SHA_SIDE" --from-ssh;                         expect_fail "a [prod] commit that is not on origin/main is rejected"; expect_has "reason shown" "not part of origin/main"

echo dirty >"$W/work/untracked.txt"
run_sub entry "$SHA_PROD" --from-ssh;                         expect_fail "untracked/uncommitted changes stop the deployment"; expect_has "reason shown" "refusing to overwrite"
expect_eq "dirty tree was not touched" "$(cat "$W/work/untracked.txt")" dirty
rm -f "$W/work/untracked.txt"
no_build_calls && pass "still nothing built or started" || fail "docker ran" "$(cat "$W/docker.log")"

run_sub entry "$SHA_PROD" --from-ssh
expect_fail "valid [prod] commit proceeds to the pre-flight (which fails in this bare fixture)"
expect_has "the exact SHA was checked out" "checked out exactly $SHA_PROD"
expect_eq "HEAD is exactly the requested SHA (detached)" "$(git -C "$W/work" rev-parse HEAD)" "$SHA_PROD"
expect_has "pre-flight stopped the run before any build" "missing file: docker-compose.yml"
no_build_calls && pass "no build/up/run happened after the failed pre-flight" || fail "docker ran" "$(cat "$W/docker.log")"

if command -v flock >/dev/null 2>&1; then
  mk_origin_repo; : >"$W/docker.log"
  ( flock 9; sleep 5 ) 9>"$W/work/.git/deploy.lock" & HOLDER=$!
  sleep 1
  run_sub entry "$SHA_PROD" --from-ssh
  expect_fail "a running deployment blocks a second one"; expect_has "reason shown" "another deployment is already running"
  wait "$HOLDER" 2>/dev/null
  no_build_calls && pass "the blocked request built nothing" || fail "docker ran" "$(cat "$W/docker.log")"
else
  skip "lock handling through the entry point (flock not installed here)"
fi

# =============================================================================================
section "Orchestration with stubs (rebuild decisions, ordering, rollback)"
FX="$W/fx"; CALLS="$W/calls.log"
mk_fx() {
  rm -rf "$FX"; git init -q -b main "$FX"
  ( cd "$FX" || exit 1
    git config user.email t@example.com; git config user.name tester; git config core.autocrlf false
    mkdir -p scripts backend/messaging/migrations frontend/src
    cp "$ROOT/deploy.sh" .; cp -r "$ROOT/scripts/." scripts/
    echo base >README.md; echo base >backend/messaging/views.py; echo base >frontend/src/App.jsx
    git add -A; git commit -q -m "base [prod]" )
}
fx_commit() { # message files...
  local msg="$1"; shift; local f
  ( cd "$FX" || exit 1
    for f in "$@"; do mkdir -p "$(dirname "$f")"; echo "$RANDOM" >>"$f"; done
    git add -A; git commit -q -m "$msg" )
  git -C "$FX" rev-parse HEAD
}
set_deployed() { mkdir -p "$FX/.git/deploy-state"; printf '%s\n' "$1" >"$FX/.git/deploy-state/last_deployed_sha"; }
deployed() { cat "$FX/.git/deploy-state/last_deployed_sha" 2>/dev/null; }

# Everything that would touch Docker or the network is replaced by a stub that records the call.
t_run() { # sha
  cd "$FX" || exit 1
  # shellcheck source=/dev/null
  . ./deploy.sh
  : >"$CALLS"
  preflight()          { :; }
  preserve_previous()  { echo "PRESERVE $1" >>"$CALLS"; }
  build_service()      { echo "BUILD $1" >>"$CALLS"; [ "${FAIL_BUILD-}" != "$1" ]; }
  stage_migrations()   { echo "MIGRATIONS" >>"$CALLS"; }
  dc()                 { echo "dc $*" >>"$CALLS"; }
  wait_healthy()       { return 0; }
  verify_backend()     { echo "VERIFY backend" >>"$CALLS"; [ "${FAIL_VERIFY-}" != backend ]; }
  verify_frontend()    { echo "VERIFY frontend" >>"$CALLS"; [ "${FAIL_VERIFY-}" != frontend ]; }
  verify_integration() { echo "VERIFY integration" >>"$CALLS"; [ "${FAIL_VERIFY-}" != integration ]; }
  rollback_service()   { echo "ROLLBACK $1" >>"$CALLS"; [ "${FAIL_ROLLBACK-}" != "$1" ]; }
  restore_latest_tag() { echo "RESTORE_TAG $1" >>"$CALLS"; }
  capture_failure_logs() { echo "CAPTURE" >>"$CALLS"; }
  cleanup_images()     { echo "CLEANUP $1" >>"$CALLS"; }
  mode_run "$1"
}
up_line() { grep -n "dc up -d --no-deps $1" "$CALLS" | head -1 | cut -d: -f1; }

mk_fx
BASE=$(git -C "$FX" rev-parse HEAD)

# first deployment: no recorded SHA
S0=$(fx_commit "first [prod]" backend/messaging/views.py)
run_sub t_run "$S0"; expect_ok "first deployment succeeds"
calls_has "first deployment builds backend" '^BUILD backend$'; calls_has "first deployment builds frontend" '^BUILD frontend$'
expect_eq "first deployment recorded its SHA" "$(deployed)" "$S0"

S1=$(fx_commit "backend src [prod]" backend/messaging/views.py)
run_sub t_run "$S1"; expect_ok "backend-only change succeeds"
calls_has   "backend-only: backend built" '^BUILD backend$'; calls_lacks "backend-only: frontend NOT built" '^BUILD frontend$'
calls_has   "backend-only: backend deployed" 'dc up -d --no-deps backend'; calls_lacks "backend-only: frontend NOT restarted" 'dc up -d --no-deps frontend'
calls_has   "backend-only: migrations stage ran" '^MIGRATIONS$'; calls_has "backend-only: backend verified" '^VERIFY backend$'
calls_lacks "backend-only: frontend not verified separately" '^VERIFY frontend$'
expect_eq "SHA recorded after backend-only deploy" "$(deployed)" "$S1"

S2=$(fx_commit "backend deps [prod]" backend/requirements.txt)
run_sub t_run "$S2"; expect_ok "backend requirements change succeeds"; calls_has "requirements: backend rebuilt" '^BUILD backend$'; calls_lacks "requirements: frontend untouched" '^BUILD frontend$'

S3=$(fx_commit "migration [prod]" backend/messaging/migrations/0006_x.py)
run_sub t_run "$S3"; expect_ok "migration change succeeds"; calls_has "migration: migrations stage ran" '^MIGRATIONS$'; calls_has "migration: backend deployed" 'dc up -d --no-deps backend'; calls_lacks "migration: frontend untouched" '^BUILD frontend$'

S4=$(fx_commit "frontend src [prod]" frontend/src/App.jsx)
run_sub t_run "$S4"; expect_ok "frontend-only change succeeds"
calls_has   "frontend-only: frontend built" '^BUILD frontend$'; calls_lacks "frontend-only: backend NOT built" '^BUILD backend$'
calls_has   "frontend-only: frontend deployed" 'dc up -d --no-deps frontend'; calls_lacks "frontend-only: backend NOT restarted" 'dc up -d --no-deps backend'
calls_lacks "frontend-only: no migration stage" '^MIGRATIONS$'; calls_has "frontend-only: frontend verified" '^VERIFY frontend$'

S5=$(fx_commit "frontend deps [prod]" frontend/package-lock.json)
run_sub t_run "$S5"; expect_ok "frontend dependency change succeeds"; calls_has "lockfile: frontend rebuilt" '^BUILD frontend$'; calls_lacks "lockfile: backend untouched" '^BUILD backend$'

S6=$(fx_commit "both [prod]" backend/messaging/views.py frontend/src/App.jsx)
run_sub t_run "$S6"; expect_ok "backend + frontend change succeeds"
calls_has "both: backend deployed" 'dc up -d --no-deps backend'; calls_has "both: frontend deployed" 'dc up -d --no-deps frontend'
[ "$(up_line backend)" -lt "$(up_line frontend)" ] && pass "both: backend is deployed BEFORE the frontend" || fail "both: wrong order" "$(cat "$CALLS")"
verify_b=$(grep -n '^VERIFY backend$' "$CALLS" | cut -d: -f1); [ "$verify_b" -lt "$(up_line frontend)" ] && pass "both: backend is verified before the frontend starts" || fail "both: backend not verified before frontend" "$(cat "$CALLS")"
calls_has "both: final integration check ran" '^VERIFY integration$'

S7=$(fx_commit "compose [prod]" docker-compose.yml)
run_sub t_run "$S7"; expect_ok "compose change succeeds"; calls_has "compose: backend rebuilt" '^BUILD backend$'; calls_has "compose: frontend rebuilt" '^BUILD frontend$'

S8=$(fx_commit "docs [prod]" README.md)
run_sub t_run "$S8"; expect_ok "documentation-only change succeeds"
calls_lacks "docs only: no image built" '^BUILD'; calls_lacks "docs only: nothing preserved" '^PRESERVE'; calls_lacks "docs only: no container touched" 'dc up'
expect_eq "docs only: SHA still recorded" "$(deployed)" "$S8"

S9=$(fx_commit "tests [prod]" backend/messaging/test_new.py)
run_sub t_run "$S9"; expect_ok "tests-only change succeeds"; calls_lacks "tests only: nothing built" '^BUILD'
S10=$(fx_commit "scripts [prod]" scripts/lib/extra.sh)
run_sub t_run "$S10"; expect_ok "deployment-script-only change succeeds"; calls_lacks "scripts only: nothing built" '^BUILD'
S11=$(fx_commit "unknown [prod]" Makefile)
run_sub t_run "$S11"; expect_ok "unknown file change succeeds"; calls_has "unknown file: backend rebuilt (conservative)" '^BUILD backend$'; calls_has "unknown file: frontend rebuilt (conservative)" '^BUILD frontend$'

S12=$(fx_commit "redeploy" README.md)
run_sub t_run "$S12"; expect_fail "a commit message without [prod] is refused by the run stage"
calls_lacks "no [prod]: nothing built" '^BUILD'

git -C "$FX" checkout -q --detach "$S11" # the run stage requires HEAD to be exactly the requested commit
set_deployed "$S11"; run_sub t_run "$S11"; expect_ok "redeploying the already-deployed commit succeeds"; calls_lacks "same commit: nothing rebuilt" '^BUILD'

# --- failures and rollback ----------------------------------------------------------------------
section "Rollback behaviour"
FAIL_VERIFY=backend; export FAIL_VERIFY
R1=$(fx_commit "r1 [prod]" docker-compose.yml); set_deployed "$S11"
run_sub t_run "$R1"; expect_fail "backend verification failure fails the deployment"
calls_has   "backend failed: backend image rolled back" '^ROLLBACK backend$'
calls_has   "backend failed: frontend image tag restored (it was built, never started)" '^RESTORE_TAG frontend$'
calls_lacks "backend failed: frontend never deployed" 'dc up -d --no-deps frontend'
calls_lacks "backend failed: frontend not rolled back (it was untouched)" '^ROLLBACK frontend$'
expect_has  "backend failed: clear result" "FAILED, previous version restored"
expect_eq   "backend failed: deployed SHA NOT advanced" "$(deployed)" "$S11"
calls_lacks "backend failed: no cleanup after a failed deployment" '^CLEANUP'
calls_has   "backend failed: failure logs captured" '^CAPTURE$'
unset FAIL_VERIFY

FAIL_VERIFY=frontend; export FAIL_VERIFY
R2=$(fx_commit "r2 [prod]" docker-compose.yml); set_deployed "$S11"
run_sub t_run "$R2"; expect_fail "frontend verification failure fails the deployment"
calls_has   "frontend failed: frontend rolled back" '^ROLLBACK frontend$'
calls_has   "frontend failed: backend rolled back too (compatible pair)" '^ROLLBACK backend$'
fl=$(grep -n '^ROLLBACK frontend$' "$CALLS" | cut -d: -f1); bl=$(grep -n '^ROLLBACK backend$' "$CALLS" | cut -d: -f1)
[ "$fl" -lt "$bl" ] && pass "frontend failed: frontend is restored before the backend" || fail "wrong rollback order" "$(cat "$CALLS")"
expect_eq   "frontend failed: deployed SHA NOT advanced" "$(deployed)" "$S11"
unset FAIL_VERIFY

FAIL_VERIFY=integration; export FAIL_VERIFY
R3=$(fx_commit "r3 [prod]" docker-compose.yml); set_deployed "$S11"
run_sub t_run "$R3"; expect_fail "final integration failure fails the deployment"
calls_has "integration failed: backend rolled back" '^ROLLBACK backend$'; calls_has "integration failed: frontend rolled back" '^ROLLBACK frontend$'
expect_eq "integration failed: deployed SHA NOT advanced" "$(deployed)" "$S11"
unset FAIL_VERIFY

FAIL_BUILD=frontend; export FAIL_BUILD
R4=$(fx_commit "r4 [prod]" docker-compose.yml); set_deployed "$S11"
run_sub t_run "$R4"; expect_fail "a failed image build stops the deployment"
calls_lacks "build failed: nothing deployed" 'dc up'; calls_lacks "build failed: no running service was rolled back (none was touched)" '^ROLLBACK'
calls_has   "build failed: built images get their latest tag moved back" '^RESTORE_TAG backend$'
expect_eq   "build failed: deployed SHA NOT advanced" "$(deployed)" "$S11"
unset FAIL_BUILD

FAIL_VERIFY=backend; FAIL_ROLLBACK=backend; export FAIL_VERIFY FAIL_ROLLBACK
R5=$(fx_commit "r5 [prod]" docker-compose.yml); set_deployed "$S11"
run_sub t_run "$R5"; expect_fail "a failed rollback is reported as a failure"
expect_has "failed rollback: loud message" "NOT fully successful"
unset FAIL_VERIFY FAIL_ROLLBACK

# --- migration approval (real stage_migrations, stubbed Docker) -------------------------------------
section "Migration approval and backup"
mk_fx
mkdir -p "$FX/backend/messaging/migrations"
printf 'from django.db import migrations\nclass Migration(migrations.Migration):\n    operations = [migrations.RemoveField(model_name="x", name="y")]\n' >"$FX/backend/messaging/migrations/0006_destructive.py"
printf 'from django.db import migrations\nclass Migration(migrations.Migration):\n    operations = [migrations.AddField(model_name="x", name="z", field=None)]\n' >"$FX/backend/messaging/migrations/0007_additive.py"
git -C "$FX" add -A; git -C "$FX" -c user.email=t@e -c user.name=t commit -q -m "migrations [prod]"
printf 'Planned operations:\nmessaging.0006_destructive\n    Remove field y from x\n' >"$W/plan_destructive.txt"
printf 'Planned operations:\nmessaging.0007_additive\n    Add field z to x\n' >"$W/plan_additive.txt"
printf 'Planned operations:\n  No planned migration operations.\n' >"$W/plan_none.txt"

t_mig() { # message plan-file
  cd "$FX" || exit 1
  # shellcheck source=/dev/null
  . ./deploy.sh
  : >"$CALLS"; rm -f "$W/migrated"
  MSG="$1"; SHA=0123456789abcdef0123456789abcdef01234567
  dc() {
    case "$*" in
      *makemigrations*) return "${MAKEMIG_RC:-0}" ;;
      *"migrate --plan"*) if [ -f "$W/migrated" ]; then cat "$W/plan_none.txt"; else cat "$PLAN_FILE"; fi ;;
      *"migrate --noinput"*) echo "MIGRATE" >>"$CALLS"; touch "$W/migrated" ;;
      *) echo "dc $*" >>"$CALLS" ;;
    esac
  }
  backup_database() { echo "BACKUP" >>"$CALLS"; return "${BACKUP_RC:-0}"; }
  stage_migrations
}
PLAN_FILE="$W/plan_destructive.txt"; export PLAN_FILE
run_sub t_mig "Remove a column [prod]";                 expect_fail "destructive migration WITHOUT [migrate-ok] is refused"
expect_has   "refusal explains the marker" "[migrate-ok]"; expect_has "refusal says nothing was changed" "NOTHING was changed"
calls_lacks  "refused: no backup was taken" '^BACKUP$'; calls_lacks "refused: migrate never ran" '^MIGRATE$'
run_sub t_mig "Remove a column [prod] [migrate-ok]";    expect_ok "destructive migration WITH [migrate-ok] is allowed"
calls_has    "approved: backup taken" '^BACKUP$'; calls_has "approved: migrate ran once" '^MIGRATE$'
[ "$(grep -c '^MIGRATE$' "$CALLS")" -eq 1 ] && pass "approved: migrations run exactly once" || fail "migrate ran more than once" "$(cat "$CALLS")"
bl=$(grep -n '^BACKUP$' "$CALLS" | cut -d: -f1); ml=$(grep -n '^MIGRATE$' "$CALLS" | cut -d: -f1)
[ "$bl" -lt "$ml" ] && pass "approved: the backup happens BEFORE the migration" || fail "backup after migrate" "$(cat "$CALLS")"
PLAN_FILE="$W/plan_additive.txt"
run_sub t_mig "Add a column [prod]";                    expect_ok "additive migration does not need [migrate-ok]"; calls_has "additive: backup still taken before migrating" '^BACKUP$'; calls_has "additive: migrated" '^MIGRATE$'
BACKUP_RC=1 run_sub t_mig "Add a column [prod]";        expect_fail "a failed backup stops everything"; calls_lacks "backup failed: migrate NOT run" '^MIGRATE$'; expect_has "backup failure reported" "backup failed"
PLAN_FILE="$W/plan_none.txt"
run_sub t_mig "No migrations [prod]";                   expect_ok "no pending migrations is fine"; calls_lacks "no pending: no backup" '^BACKUP$'; calls_lacks "no pending: no migrate" '^MIGRATE$'
PLAN_FILE="$W/plan_additive.txt"
MAKEMIG_RC=1 run_sub t_mig "Add a column [prod]";       expect_fail "uncommitted model changes (makemigrations --check) stop the deployment"; calls_lacks "uncommitted: no backup" '^BACKUP$'; calls_lacks "uncommitted: no migrate" '^MIGRATE$'

# --- orchestration: refused migration leaves running containers alone -------------------------------
mk_fx
FAIL_STAGE=1
t_mig_run() {
  cd "$FX" || exit 1
  # shellcheck source=/dev/null
  . ./deploy.sh
  : >"$CALLS"
  preflight() { :; }; preserve_previous() { :; }; build_service() { echo "BUILD $1" >>"$CALLS"; }
  stage_migrations() { die "refused by the migration check"; }
  dc() { echo "dc $*" >>"$CALLS"; }; restore_latest_tag() { echo "RESTORE_TAG $1" >>"$CALLS"; }
  rollback_service() { echo "ROLLBACK $1" >>"$CALLS"; }; capture_failure_logs() { :; }
  mode_run "$1"
}
M1=$(fx_commit "needs migration [prod]" backend/messaging/views.py)
run_sub t_mig_run "$M1"; expect_fail "a refused migration fails the deployment"
calls_lacks "refused migration: no container was started" 'dc up'
calls_lacks "refused migration: no running service was rolled back (none was touched)" '^ROLLBACK'
calls_has   "refused migration: the built image's latest tag was moved back" '^RESTORE_TAG backend$'

# --- docker helper functions with fakes ----------------------------------------------------------------
section "Image preservation, rollback helper, health wait"
t_preserve() { # scenario
  load_libs; : >"$CALLS"
  container_of() { [ "$1" = backend ] && [ "${HAVE_CONTAINER-}" = yes ] && echo cid123; }
  docker() {
    case "$1" in
      inspect) echo "sha256:runningimage0000000000000000000000000000000000000000000000000000" ;;
      image) echo "sha256:latestimage" ;;
      tag) echo "TAG $2 $3" >>"$CALLS" ;;
    esac
  }
  preserve_previous backend
}
HAVE_CONTAINER=yes run_sub t_preserve;  expect_ok "preserve: a running container's image becomes :previous"
calls_has "preserve: tagged from the RUNNING container's image id" 'TAG sha256:runningimage.* whatsapp-automation-bot-backend:previous'
t_first() { load_libs; : >"$CALLS"; container_of() { :; }; docker() { case "$1" in tag) echo "TAG $2 $3" >>"$CALLS" ;; image) return 1 ;; esac; }; preserve_previous backend; }
run_sub t_first; expect_ok "preserve: first deployment (no image yet) is handled"; expect_has "preserve: says nothing to preserve" "nothing to preserve"; calls_lacks "preserve: no tag created" 'TAG'

t_rollback() { # have-previous
  load_libs; : >"$CALLS"
  image_exists() { [ "$HAVE_PREVIOUS" = yes ]; }
  docker() { [ "$1" = tag ] && echo "TAG $2 $3" >>"$CALLS"; return 0; }
  dc() { echo "dc $*" >>"$CALLS"; }
  wait_healthy() { return 0; }
  rollback_service backend
}
HAVE_PREVIOUS=yes run_sub t_rollback; expect_ok "rollback_service restores a healthy previous image"
calls_has "rollback: :previous is moved back to :latest" 'TAG whatsapp-automation-bot-backend:previous whatsapp-automation-bot-backend:latest'
calls_has "rollback: ONLY that service is recreated, without building" 'dc up -d --no-deps --no-build backend'
calls_lacks "rollback: the other service is not touched" 'frontend'
HAVE_PREVIOUS=no run_sub t_rollback; expect_fail "rollback without a previous image reports failure"; expect_has "rollback: explains why" "no previous image"

t_wait() { # statuses...
  load_libs; local -a seq=("$@")
  echo 0 >"$W/wait.idx" # the counter lives in a file: command substitution runs in a subshell
  health_status() { local i; i=$(cat "$W/wait.idx"); echo "${seq[$i]:-starting}"; echo $((i + 1)) >"$W/wait.idx"; }
  sleep() { :; }
  wait_healthy backend 12
}
run_sub t_wait starting starting healthy;  expect_ok   "wait_healthy succeeds once the container is healthy"
run_sub t_wait starting unhealthy;         expect_fail "wait_healthy fails fast on an unhealthy container"
run_sub t_wait starting starting starting starting starting starting; expect_fail "wait_healthy times out on a container that never becomes healthy"
run_sub t_wait missing;                    expect_fail "wait_healthy fails when the container does not exist"

t_expect_json() { # body-with-status
  load_libs
  curl() { printf '%s' "$FAKE_RESPONSE"; }
  expect_health_json http://127.0.0.1:8003/api/health/ "backend health"
}
FAKE_RESPONSE=$'{"status": "ok"}\n200' run_sub t_expect_json;          expect_ok   "health check accepts 200 + status ok"
FAKE_RESPONSE=$'{"status": "unavailable"}\n503' run_sub t_expect_json; expect_fail "health check rejects 503"
FAKE_RESPONSE=$'<html>login</html>\n200' run_sub t_expect_json;        expect_fail "health check rejects a 200 that is not the health JSON"

# --- cleanup is scoped -----------------------------------------------------------------------------------
t_cleanup() {
  load_libs; : >"$CALLS"
  docker() {
    case "$1 $2" in
      "image ls")
        case "$3" in
          whatsapp-automation-bot-backend) printf 'latest\nprevious\nAAAA1111\noldsha01\n<none>\n' ;;
          whatsapp-automation-bot-frontend) printf 'latest\nprevious\nAAAA1111\n' ;;
          *) printf 'dangling1\n' ;; # the --filter form: ids
        esac ;;
      "rmi "*) echo "RMI $2" >>"$CALLS" ;;
    esac
    return 0
  }
  cleanup_images AAAA1111
}
run_sub t_cleanup; expect_ok "cleanup runs"
calls_has   "cleanup: removes an old SHA tag of this project" '^RMI whatsapp-automation-bot-backend:oldsha01$'
calls_lacks "cleanup: keeps :latest" ':latest'; calls_lacks "cleanup: keeps :previous" ':previous'; calls_lacks "cleanup: keeps the deployed SHA tag" ':AAAA1111'
calls_lacks "cleanup: never uses prune" 'prune'
if grep -rnE 'docker (system|image|volume|container) prune|compose down|docker volume rm|docker rm -f|image prune' \
     --include='*.sh' --exclude='test-deploy.sh' "$ROOT/deploy.sh" "$ROOT/scripts" \
   | grep -vE ':[0-9]+:[[:space:]]*#' >"$W/forbidden.txt"; then
  fail "forbidden global/destructive Docker command found in code (not a comment)" "$(cat "$W/forbidden.txt")"
else
  pass "no prune, down, or volume-removal command is used in any script (comments excluded)"
fi

printf '\n=========================================\n'
printf 'passed: %d   failed: %d   skipped: %d\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
