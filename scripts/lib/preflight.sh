# shellcheck shell=bash
# Pre-flight checks that run before anything is built or started. Sourced by deploy.sh.
# Only variable NAMES are ever printed, never values.

ENV_FILE=backend/.env.prod
env_get() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }

preflight() {
  local f v placeholders key busy own

  step "Pre-flight: files"
  for f in docker-compose.yml backend/Dockerfile frontend/Dockerfile frontend/nginx.conf \
           backend/.dockerignore frontend/.dockerignore backend/constraints.txt "$ENV_FILE"; do
    [ -f "$f" ] || die "missing file: $f"
  done
  ok "compose file, Dockerfiles, nginx.conf, .dockerignore files and $ENV_FILE exist"

  step "Pre-flight: production environment ($ENV_FILE), names only"
  placeholders=$(grep -E '^[A-Z_]+=.*REPLACE_WITH_' "$ENV_FILE" | cut -d= -f1 || true) # no match is the normal case
  if [ -n "$placeholders" ]; then
    echo "$placeholders" | sed 's/^/    - /'
    die "fill in every REPLACE_WITH_ value in $ENV_FILE first"
  fi
  ok "no REPLACE_WITH_ placeholders"
  for v in DEBUG SECRET_KEY ALLOWED_HOSTS FRONTEND_ORIGIN CSRF_TRUSTED_ORIGINS HTTPS_ENABLED DATABASE_PATH \
           WHATSAPP_ACCESS_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_GRAPH_API_VERSION \
           WHATSAPP_TEMPLATE_NAME WHATSAPP_TEMPLATE_LANG WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
    [ -n "$(env_get "$v")" ] || die "$v is missing or empty in $ENV_FILE"
  done
  ok "all required variables are set"
  # Every sign-in needs a code emailed to the person, so without a working mail setup nobody could log in.
  if [ "$(env_get LOGIN_OTP_REQUIRED | tr '[:upper:]' '[:lower:]')" != "false" ]; then
    for v in EMAIL_HOST EMAIL_HOST_USER EMAIL_HOST_PASSWORD; do
      [ -n "$(env_get "$v")" ] || die "$v is missing or empty in $ENV_FILE (needed to email the sign-in code; add it before deploying)"
    done
    ok "email settings for the sign-in code are set"
  fi
  [ "$(env_get DEBUG)" = "False" ] || die "DEBUG must be False"
  ok "DEBUG=False"
  key=$(env_get SECRET_KEY)
  { [ "${#key}" -ge 50 ] && [ "$key" != "insecure-dev-key-change-me" ]; } || die "SECRET_KEY looks like a development value"
  ok "SECRET_KEY is a long production value"
  [ "$(env_get HTTPS_ENABLED)" = "True" ] || die "HTTPS_ENABLED must be True in production"
  ok "HTTPS_ENABLED=True"
  [ "$(env_get DATABASE_PATH)" = "/data/db.sqlite3" ] || die "DATABASE_PATH must be /data/db.sqlite3"

  step "Pre-flight: compose, nginx and ignore rules"
  grep -q 'backend_data:/data' docker-compose.yml || die "the backend_data volume is not mounted at /data"
  ok "SQLite lives on the persistent volume backend_data (/data/db.sqlite3)"
  grep -q 'VITE_API_BASE_URL: /api' docker-compose.yml || die "frontend API base URL must be /api"
  ok "frontend API base URL is /api"
  grep -q '127.0.0.1:8000:3000' docker-compose.yml || die "frontend must be mapped 127.0.0.1:8000:3000"
  grep -q '127.0.0.1:8003:8000' docker-compose.yml || die "backend must be mapped 127.0.0.1:8003:8000"
  ok "ports: frontend 127.0.0.1:8000->3000, backend 127.0.0.1:8003->8000"
  grep -Eq 'location ~ \^/\(api\|admin\|webhook\)' frontend/nginx.conf && grep -q 'proxy_pass http://backend:8000' frontend/nginx.conf \
    || die "nginx must proxy /api, /admin and /webhook to http://backend:8000"
  ok "nginx proxies /api, /admin and /webhook to http://backend:8000"
  if git rev-parse --git-dir >/dev/null 2>&1; then
    git check-ignore -q "$ENV_FILE" || die "$ENV_FILE is not git-ignored"
    [ -z "$(git ls-files | grep -E '(^|/)\.env($|\.(dev|prod)$)' || true)" ] || die "an environment file is tracked by Git"
    ok "$ENV_FILE is git-ignored and no env file is tracked"
  fi
  for f in backend frontend; do
    grep -Eq '^\.env\.\*' "$f/.dockerignore" || die "$f/.dockerignore does not exclude .env.* files"
  done
  ok ".dockerignore excludes every .env.* file, so no secrets enter the build context"

  step "Pre-flight: Docker and ports"
  docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon (is this user allowed to run docker?)"
  ok "Docker daemon reachable"
  command -v ss >/dev/null || die "'ss' not found: cannot verify that the ports are free"
  own=$(dc ps -q 2>/dev/null | wc -l | tr -d ' ')
  busy=$(ss -ltnH '( sport = :8000 or sport = :8003 )' || true)
  if [ -n "$busy" ] && [ "$own" = "0" ]; then
    echo "$busy" | sed 's/^/    /'
    die "port 8000 and/or 8003 is in use by something other than this project. Nothing was changed; do not pick another port without approval."
  fi
  if [ -n "$busy" ]; then ok "ports are held by this project's own containers (redeploy)"; else ok "ports 8000 and 8003 are free"; fi
  chmod 600 "$ENV_FILE"
  dc config --quiet
  ok "docker compose configuration is valid"
}
