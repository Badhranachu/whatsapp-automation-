# shellcheck shell=bash
# Docker helpers, scoped to THIS Compose project only. Sourced by deploy.sh.
# Nothing here uses `down`, volume commands, `docker system prune` or `docker image prune`.

PROJECT=whatsapp-automation-bot

dc() { docker compose "$@"; }
repo_of() { printf '%s-%s' "$PROJECT" "$1"; }                 # image repository of a service
short_id() { local x="${1#sha256:}"; printf '%s' "${x:0:12}"; }
image_exists() { docker image inspect "$1" >/dev/null 2>&1; }
container_of() { { dc ps -a -q "$1" 2>/dev/null || true; } | head -n1; } # no container is a normal answer

# The image that is running RIGHT NOW is the known-good one. Taken from the container, not from the
# `latest` tag, so an interrupted earlier deployment can never make an unverified image look good.
current_good_image() {
  local cid id=""
  cid=$(container_of "$1")
  if [ -n "$cid" ]; then id=$(docker inspect --format '{{.Image}}' "$cid" 2>/dev/null || true); fi
  if [ -z "$id" ]; then id=$(docker image inspect --format '{{.Id}}' "$(repo_of "$1"):latest" 2>/dev/null || true); fi
  printf '%s' "$id"
}

# Keep the currently running image as <repo>:previous (the rollback target).
preserve_previous() {
  local svc="$1" repo id
  repo=$(repo_of "$svc")
  id=$(current_good_image "$svc")
  if [ -z "$id" ]; then
    info "$svc: no existing image (first deployment): nothing to preserve"
    return 0
  fi
  docker tag "$id" "$repo:previous" || return 1
  ok "$svc: running image preserved as $repo:previous ($(short_id "$id"))"
}

# Build with BuildKit (layer cache is reused automatically) and tag the result with the commit SHA.
build_service() {
  local svc="$1" sha="$2" repo
  repo=$(repo_of "$svc")
  DOCKER_BUILDKIT=1 dc build "$svc" || return 1
  docker tag "$repo:latest" "$repo:$sha" || return 1
}

health_status() {
  local cid
  cid=$(container_of "$1")
  [ -n "$cid" ] || { echo missing; return 0; }
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealthcheck{{end}}' "$cid" 2>/dev/null || echo unknown
}

# wait_healthy <service> [timeout seconds]: succeeds only when Docker reports the container healthy.
wait_healthy() {
  local svc="$1" timeout="${2:-120}" waited=0 st
  while :; do
    st=$(health_status "$svc")
    case "$st" in
      healthy) return 0 ;;
      unhealthy|missing|nohealthcheck) return 1 ;;
    esac
    [ "$waited" -lt "$timeout" ] || return 1
    sleep 3
    waited=$((waited + 3))
  done
}

# ---- application-level checks (not just "the container is running") -----------------------------
# curl prints 000 when it cannot connect, so a failure still yields a usable value.
http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || true; }

expect_code() { # url expected description
  local got
  got=$(http_code "$1")
  if [ "$got" = "$2" ]; then ok "$3 ($got)"; return 0; fi
  info "FAILED: $3: expected HTTP $2 from $1 but got $got"
  return 1
}

expect_health_json() { # url description
  local out code body re='"status": *"ok"'
  out=$(curl -s --max-time 10 -w '\n%{http_code}' "$1" 2>/dev/null || true)
  code="${out##*$'\n'}"
  body="${out%$'\n'*}"
  if [ "$code" = 200 ] && [[ "$body" =~ $re ]]; then ok "$2 (200, status ok)"; return 0; fi
  info "FAILED: $2: expected HTTP 200 with status ok from $1 but got $code"
  return 1
}

# Errors in the service log since a point in time (the known, harmless gunicorn control-socket line is ignored).
check_logs() { # service since
  local bad
  bad=$(dc logs --no-color --since "$2" "$1" 2>&1 | grep -Ei 'Traceback|CRITICAL|\[ERROR\]' | grep -v 'Control server error' || true)
  if [ -z "$bad" ]; then ok "$1 log has no errors since the new container started"; return 0; fi
  info "FAILED: $1 logged errors:"
  printf '%s\n' "$bad" | mask_secrets | head -n 20 | sed 's/^/        /'
  return 1
}

verify_backend() { # since
  local rc=0
  expect_health_json http://127.0.0.1:8003/api/health/ "backend /api/health/ (Django and database)" || rc=1
  expect_code http://127.0.0.1:8003/api/auth/me/ 401 "protected API still requires login" || rc=1
  expect_code http://127.0.0.1:8003/webhook 403 "webhook still refuses a bad verification" || rc=1
  check_logs backend "$1" || rc=1
  return "$rc"
}

verify_frontend() {
  local rc=0 re='id="root"' page
  expect_code http://127.0.0.1:8000/ 200 "frontend serves the app" || rc=1
  page=$(curl -s --max-time 10 http://127.0.0.1:8000/ 2>/dev/null || true)
  if [[ "$page" =~ $re ]]; then ok "frontend page contains the app root"; else info "FAILED: frontend page has no app root"; rc=1; fi
  expect_code http://127.0.0.1:8000/manifest.webmanifest 200 "PWA manifest is served" || rc=1
  if curl -sI --max-time 10 http://127.0.0.1:8000/sw.js 2>/dev/null | tr -d '\r' | grep -qi '^cache-control:.*no-cache'; then
    ok "service worker is served with no-cache"
  else
    info "FAILED: /sw.js is not served with Cache-Control: no-cache"; rc=1
  fi
  return "$rc"
}

verify_integration() {
  local rc=0
  expect_code http://127.0.0.1:8000/ 200 "frontend (port 8000)" || rc=1
  expect_health_json http://127.0.0.1:8000/api/health/ "frontend nginx -> backend (/api/health/ through port 8000)" || rc=1
  expect_code http://127.0.0.1:8000/api/auth/me/ 401 "API through the frontend still requires login" || rc=1
  expect_code http://127.0.0.1:8000/webhook 403 "webhook reaches Django through the frontend proxy" || rc=1
  expect_health_json http://127.0.0.1:8003/api/health/ "backend directly (port 8003)" || rc=1
  return "$rc"
}

# ---- rollback ------------------------------------------------------------------------------------
# Put the preserved image back and recreate ONLY that service. Succeeds when it is healthy again.
rollback_service() {
  local svc="$1" repo
  repo=$(repo_of "$svc")
  image_exists "$repo:previous" || { warn "$svc: there is no previous image to restore (first deployment?)"; return 1; }
  docker tag "$repo:previous" "$repo:latest" || return 1
  dc up -d --no-deps --no-build "$svc" || return 1
  wait_healthy "$svc" 120
}

# An image that was built but never started: only move the `latest` tag back to the good image.
restore_latest_tag() {
  local svc="$1" repo
  repo=$(repo_of "$svc")
  image_exists "$repo:previous" || return 0
  docker tag "$repo:previous" "$repo:latest"
}

capture_failure_logs() { # state_dir sha service...
  local dir="$1" sha="$2" f s
  shift 2
  mkdir -p "$dir"
  f="$dir/$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:12}.log"
  {
    echo "commit: $sha"
    echo "time: $(date -u)"
    dc ps 2>&1
    for s in "$@"; do
      echo "--- logs: $s (last 200 lines)"
      dc logs --no-color --tail=200 "$s" 2>&1
    done
  } | mask_secrets >"$f"
  info "failure details saved to $f (secrets masked); last lines:"
  tail -n 40 "$f" | sed 's/^/        /'
}

# ---- cleanup (scoped to this project) ------------------------------------------------------------
# Keeps: latest, previous and the tag of the commit that was just deployed. Removes other tags of this
# project's two image repositories, and untagged images that carry this project's label. A tag whose
# image is still used by a container cannot be removed by Docker and is simply kept.
cleanup_images() { # current_sha
  local sha="$1" svc repo tag id
  for svc in backend frontend; do
    repo=$(repo_of "$svc")
    while IFS= read -r tag; do
      case "$tag" in ''|'<none>'|latest|previous|"$sha") continue ;; esac
      if docker rmi "$repo:$tag" >/dev/null 2>&1; then ok "removed old image $repo:$tag"; else warn "kept $repo:$tag (in use or could not be removed)"; fi
    done < <(docker image ls "$repo" --format '{{.Tag}}')
  done
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    if docker rmi "$id" >/dev/null 2>&1; then ok "removed unused image $id"; else warn "kept unused image $id (in use or could not be removed)"; fi
  done < <(docker image ls --filter dangling=true --filter "label=com.nexston.project=$PROJECT" -q)
}
