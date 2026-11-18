#!/usr/bin/env bash
# Safe production deploy for THIS project only. Run on the Ubuntu server from the project directory:
#
#   bash deploy.sh --check-only   # validations only: builds and starts nothing
#   bash deploy.sh                # validate, build, start, verify
#
# It never prints secret values, and it never uses `docker compose down`, volume deletion or any
# global prune. It only touches this Compose project ("whatsapp-automation-bot").
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=backend/.env.prod
CHECK_ONLY=false
[ "${1:-}" = "--check-only" ] && CHECK_ONLY=true

fail() { echo "STOP: $*" >&2; exit 1; }
ok()   { echo "  ok  - $*"; }
get()  { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }

echo "== 1. Files"
for f in docker-compose.yml backend/Dockerfile frontend/Dockerfile frontend/nginx.conf \
         backend/.dockerignore frontend/.dockerignore "$ENV_FILE"; do
  [ -f "$f" ] || fail "missing file: $f"
done
ok "Dockerfiles, docker-compose.yml, nginx.conf, .dockerignore files and $ENV_FILE exist"

echo "== 2. Production environment ($ENV_FILE) - only variable NAMES are shown"
placeholders=$(grep -E '^[A-Z_]+=.*REPLACE_WITH_' "$ENV_FILE" | cut -d= -f1 || true)
if [ -n "$placeholders" ]; then
  echo "  placeholders still present in:"; echo "$placeholders" | sed 's/^/    - /'
  fail "fill in every REPLACE_WITH_ value, then run this again"
fi
ok "no REPLACE_WITH_ placeholders"
for v in DEBUG SECRET_KEY ALLOWED_HOSTS FRONTEND_ORIGIN CSRF_TRUSTED_ORIGINS HTTPS_ENABLED DATABASE_PATH \
         WHATSAPP_ACCESS_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_GRAPH_API_VERSION \
         WHATSAPP_TEMPLATE_NAME WHATSAPP_TEMPLATE_LANG WHATSAPP_VERIFY_TOKEN WHATSAPP_APP_SECRET; do
  [ -n "$(get "$v")" ] || fail "$v is missing or empty in $ENV_FILE"
done
ok "all 14 required variables are set"
[ "$(get DEBUG)" = "False" ] || fail "DEBUG must be False"
ok "DEBUG=False"
key=$(get SECRET_KEY)
{ [ "${#key}" -ge 50 ] && [ "$key" != "insecure-dev-key-change-me" ]; } || fail "SECRET_KEY looks like a development value (too short or the dev default)"
ok "SECRET_KEY is a long production value"
[ "$(get HTTPS_ENABLED)" = "True" ] || fail "HTTPS_ENABLED must be True in production"
ok "HTTPS_ENABLED=True"

echo "== 3. Compose, Nginx and ignore rules"
[ "$(get DATABASE_PATH)" = "/data/db.sqlite3" ] || fail "DATABASE_PATH must be /data/db.sqlite3"
grep -q 'backend_data:/data' docker-compose.yml || fail "the backend_data volume is not mounted at /data"
ok "SQLite lives at /data/db.sqlite3 on the persistent volume backend_data"
grep -q 'VITE_API_BASE_URL: /api' docker-compose.yml || fail "frontend API base URL must be /api"
ok "frontend API base URL is /api"
grep -q '127.0.0.1:8000:3000' docker-compose.yml || fail "frontend must be mapped 127.0.0.1:8000:3000"
grep -q '127.0.0.1:8003:8000' docker-compose.yml || fail "backend must be mapped 127.0.0.1:8003:8000"
ok "ports: frontend 127.0.0.1:8000->3000, backend 127.0.0.1:8003->8000"
grep -Eq 'location ~ \^/\(api\|admin\|webhook\)' frontend/nginx.conf && grep -q 'proxy_pass http://backend:8000' frontend/nginx.conf \
  || fail "nginx must proxy /api, /admin and /webhook to http://backend:8000"
ok "nginx proxies /api, /admin and /webhook to http://backend:8000"
if git rev-parse --git-dir >/dev/null 2>&1; then
  git check-ignore -q "$ENV_FILE" || fail "$ENV_FILE is not git-ignored"
  [ -z "$(git ls-files | grep -E '(^|/)\.env($|\.(dev|prod)$)' || true)" ] || fail "an environment file is tracked by Git"
  ok "$ENV_FILE is git-ignored and no env file is tracked"
fi
for d in backend frontend; do
  grep -Eq '^\.env\.\*' "$d/.dockerignore" || fail "$d/.dockerignore does not exclude .env.* files"
done
ok ".dockerignore excludes every .env.* file, so no secrets enter the build context"

echo "== 4. Ports 8000 and 8003 on this server"
command -v ss >/dev/null || fail "'ss' not found: cannot verify that the ports are free"
own=$(docker compose ps -q 2>/dev/null | wc -l | tr -d ' ')
busy=$(ss -ltnH '( sport = :8000 or sport = :8003 )' || true)
if [ -n "$busy" ] && [ "$own" = "0" ]; then
  echo "$busy" | sed 's/^/    /'
  fail "port 8000 and/or 8003 is already in use by something else. Nothing was changed. Tell the owner, do not pick another port without approval."
fi
if [ -n "$busy" ]; then ok "ports held by this project's own running containers (redeploy)"; else ok "ports 8000 and 8003 are free"; fi

chmod 600 "$ENV_FILE"; ok "chmod 600 $ENV_FILE"
docker compose config --quiet; ok "docker compose config is valid"

if $CHECK_ONLY; then echo; echo "All checks passed (--check-only: nothing was built or started)."; exit 0; fi

echo "== 5. Build and start (this project only)"
docker compose build
docker compose up -d

echo "== 6. Wait for healthy containers (up to 3 minutes)"
for svc in backend frontend; do
  cid=$(docker compose ps -q "$svc")
  for _ in $(seq 1 36); do
    st=$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo none)
    [ "$st" = "healthy" ] && break
    sleep 5
  done
  [ "$st" = "healthy" ] || { docker compose logs --tail=60 "$svc" | sed -E 's/(verify_token|hub\.challenge)=[^& "]*/\1=***/g'; fail "$svc is not healthy (status: $st)"; }
  ok "$svc is healthy"
done

echo "== 7. HTTP verification"
code() { curl -s -o /dev/null -w '%{http_code}' "$1"; }
[ "$(code http://127.0.0.1:8000/)" = "200" ] && ok "frontend answers 200 on 127.0.0.1:8000" || fail "frontend did not answer 200"
c=$(code http://127.0.0.1:8003/api/auth/me/); [ "$c" = "401" ] && ok "backend 127.0.0.1:8003 answers 401 (running; login required, as designed)" || fail "backend /api/auth/me/ returned $c, expected 401"
c=$(code http://127.0.0.1:8000/api/auth/me/); [ "$c" = "401" ] && ok "frontend Nginx -> backend works (/api answers 401 through port 8000)" || fail "/api through the frontend returned $c, expected 401"
c=$(code http://127.0.0.1:8000/webhook); [ "$c" = "403" ] && ok "/webhook reaches Django through Nginx (403 = verification refused, as designed)" || fail "/webhook returned $c, expected 403"

echo "== 8. Database persistence and migrations"
docker compose exec -T backend sh -c 'test -s /data/db.sqlite3' && ok "database file exists in the volume (/data/db.sqlite3)" || fail "no database file in /data"
pending=$(docker compose exec -T backend python manage.py showmigrations --plan | grep -c '^\[ \]' || true)
[ "$pending" = "0" ] && ok "migrations: all applied" || fail "$pending migrations still pending"
docker compose restart backend >/dev/null
cid=$(docker compose ps -q backend)
for _ in $(seq 1 24); do [ "$(docker inspect --format '{{.State.Health.Status}}' "$cid")" = "healthy" ] && break; sleep 5; done
docker compose exec -T backend sh -c 'test -s /data/db.sqlite3' && ok "database survived a backend restart" || fail "database missing after restart"

echo "== 9. Status and recent logs (verify tokens hidden)"
docker compose ps
for svc in frontend backend; do
  echo "--- $svc (last 100 lines)"
  docker compose logs --tail=100 "$svc" | sed -E 's/(verify_token|hub\.challenge)=[^& "]*/\1=***/g'
done

echo
echo "Deployed. Create the production administrator yourself (it asks for a password):"
echo "  docker compose exec backend python manage.py createsuperuser"
