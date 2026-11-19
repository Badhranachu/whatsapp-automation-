# shellcheck shell=bash
# Database backup wrapper. Sourced by deploy.sh.
#
# Retention policy: the 14 newest backups are kept in the volume (/data/backups) and 14 on the host
# (/var/backups/whatsapp-automation-bot). Backups are taken only when a deployment has pending
# migrations. File names: db-<UTC timestamp>-<commit sha, 12 chars>.sqlite3
#
# Manual restore (backend stopped first), for example:
#   docker compose stop backend
#   docker run --rm -v whatsapp-automation-bot_backend_data:/data -v /var/backups/whatsapp-automation-bot:/b \
#       --entrypoint cp whatsapp-automation-bot-backend:latest /b/<file> /data/db.sqlite3
#   docker compose up -d --no-deps backend

HOST_BACKUP_DIR=/var/backups/whatsapp-automation-bot

backup_database() { # commit_sha
  local sha="$1" out
  mkdir -p "$HOST_BACKUP_DIR" && chmod 700 "$HOST_BACKUP_DIR" || return 1
  # one-off container as root: it must write into the host directory; the application container is untouched
  out=$(dc run --rm --no-deps -T --user 0 -v "$HOST_BACKUP_DIR:/hostbackup" backend python - "$sha" <scripts/backup_sqlite.py) || return 1
  printf '%s\n' "$out" | grep -E 'BACKUP_(OK|SKIPPED)' | sed 's/^/        /'
  printf '%s\n' "$out" | grep -qE 'BACKUP_(OK|SKIPPED)'
}
