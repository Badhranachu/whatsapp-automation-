# shellcheck shell=bash
# Change detection: which services must be rebuilt for a set of changed files.
# Sourced by deploy.sh. Conservative by design: a path it does not recognise rebuilds BOTH services.

classify_path() {
  case "$1" in
    # --- no effect on any running service -------------------------------------------------
    *.md|.gitignore|LICENSE|LICENSE.*) echo docs ;;
    backend/.env.example|frontend/.env.example) echo docs ;;
    frontend/.oxlintrc.json|frontend/.gitignore) echo docs ;; # lint / ignore config, not in the image
    .github/*) echo ci ;;
    deploy.sh|scripts/*) echo scripts ;;                        # takes effect on the next deployment
    # --- docker compose ------------------------------------------------------------------
    docker-compose.yml|docker-compose.yaml|compose.yml|compose.yaml) echo compose ;;
    # --- backend ----------------------------------------------------------------------------
    backend/requirements.txt|backend/constraints.txt) echo backend-deps ;;
    backend/Dockerfile|backend/.dockerignore) echo backend-docker ;;
    backend/messaging/migrations/*) echo backend-migrations ;;
    backend/messaging/test_*.py|backend/messaging/tests.py) echo tests ;; # never executed in production
    backend/*) echo backend-src ;;
    # --- frontend ---------------------------------------------------------------------------
    frontend/package.json|frontend/package-lock.json) echo frontend-deps ;;
    frontend/Dockerfile|frontend/.dockerignore|frontend/nginx.conf) echo frontend-docker ;;
    frontend/*) echo frontend-src ;;
    # --- unknown: be conservative ----------------------------------------------------------
    *) echo other ;;
  esac
}

# Reads changed paths (one per line) on stdin and prints key=value lines describing the plan.
detect_plan() {
  local build_backend=no build_frontend=no migrations=no any=no cats="" p c only_inert=yes
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    any=yes
    c=$(classify_path "$p")
    if ! in_list "$c" "$cats"; then cats="$cats $c"; fi
    case "$c" in
      backend-src|backend-deps|backend-docker|compose|other) build_backend=yes ;;
      backend-migrations) build_backend=yes; migrations=yes ;;
    esac
    case "$c" in
      frontend-src|frontend-deps|frontend-docker|compose|other) build_frontend=yes ;;
    esac
    case "$c" in docs|ci|scripts|tests) ;; *) only_inert=no ;; esac
  done
  local summary
  if [ "$any" = no ]; then
    summary="no changes since the last deployed commit"
  elif [ "$build_backend" = no ] && [ "$build_frontend" = no ]; then
    if [ "$only_inert" = yes ] && ! in_list scripts "$cats" && ! in_list tests "$cats" && ! in_list ci "$cats"; then
      summary="documentation only"
    else
      summary="no service-affecting changes (documentation, tests, CI or deployment scripts only)"
    fi
  else
    summary="service-affecting changes"
  fi
  printf 'build_backend=%s\n' "$build_backend"
  printf 'build_frontend=%s\n' "$build_frontend"
  printf 'migrations=%s\n' "$migrations"
  printf 'any_change=%s\n' "$any"
  printf 'categories=%s\n' "${cats# }"
  printf 'summary=%s\n' "$summary"
}

# No usable "previous deployed commit": rebuild everything.
detect_plan_all() {
  printf 'build_backend=yes\nbuild_frontend=yes\nmigrations=unknown\nany_change=yes\ncategories=unknown\nsummary=first deployment (no previously deployed commit recorded)\n'
}

# plan_get <key> <plan-text>
plan_get() { printf '%s\n' "$2" | sed -n "s/^$1=//p" | head -n1; }
