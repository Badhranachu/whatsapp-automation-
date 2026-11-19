# shellcheck shell=bash
# Shared helpers for deploy.sh. This file is sourced, never run directly.

SHA_RE='^[0-9a-f]{40}$'

step() { printf '\n== %s\n' "$*"; }
ok()   { printf '  ok  - %s\n' "$*"; }
info() { printf '        %s\n' "$*"; }
warn() { printf '  WARN - %s\n' "$*" >&2; }
die()  { printf 'STOP: %s\n' "$*" >&2; exit 1; }

# A commit id must be exactly 40 lowercase hexadecimal characters.
is_sha() { [[ "${1-}" =~ $SHA_RE ]]; }
require_sha() { is_sha "${1-}" || die "not a valid 40-character lowercase hexadecimal commit SHA"; }

# Commit-message markers. The message is read from Git on the server, never from the SSH request.
msg_has_tag() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }
gate_prod() { msg_has_tag "$1" '[prod]'; }
gate_migrate_ok() { msg_has_tag "$1" '[migrate-ok]'; }

# Mask anything that looks like a secret before it is shown or saved (webhook verify token in
# query strings, Meta access tokens, bearer headers, key=value secrets).
mask_secrets() {
  sed -E \
    -e 's/((hub\.)?verify_token|access_token|app_secret|secret_key|password)=[^&[:space:]"]+/\1=***/Ig' \
    -e 's/EAA[A-Za-z0-9]{20,}/EAA***/g' \
    -e 's/(Authorization:[[:space:]]*Bearer[[:space:]]+)[^[:space:]]+/\1***/Ig'
}

# Exclusive deployment lock. The lock is held on file descriptor 9 until the process ends, and the
# kernel releases it automatically even if the script is killed, so it can never go stale.
acquire_lock() {
  command -v flock >/dev/null 2>&1 || die "flock is required but not installed"
  exec 9>"$1" || die "cannot open the lock file $1"
  flock -n 9 || die "another deployment is already running (lock held). Nothing was changed."
}

in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
