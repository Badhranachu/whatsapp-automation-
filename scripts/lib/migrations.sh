# shellcheck shell=bash
# Migration safety helpers. Sourced by deploy.sh.

# Operations that can lose data or change existing data. These need "[migrate-ok]" in the commit message.
DESTRUCTIVE_RE='migrations\.(RemoveField|DeleteModel|RenameModel|RenameField|AlterField|AlterModelTable|RunPython|RunSQL|SeparateDatabaseAndState|RemoveIndex|RemoveConstraint)\b'

# stdin: text of `manage.py migrate --plan`. $1: repository root.
# Prints the repository's own migration files that appear in the plan (Django's built-in apps are not
# in the repository and are ignored).
plan_migration_files() {
  local root="$1" line app name f
  while IFS= read -r line; do
    if [[ "$line" =~ ^([a-z_][a-z0-9_]*)\.([0-9]{4}_[A-Za-z0-9_]+)$ ]]; then
      app="${BASH_REMATCH[1]}"
      name="${BASH_REMATCH[2]}"
      f="$root/backend/$app/migrations/$name.py"
      if [ -f "$f" ]; then printf '%s\n' "$f"; fi
    fi
  done
}

# scan_destructive <migration files...>
# Prints "file: line" for every risky operation. Exit status 0 = something risky was found, 1 = clean.
scan_destructive() {
  local f out risky=1
  for f in "$@"; do
    [ -f "$f" ] || continue
    # grep exits 1 when nothing matches; that is the normal "clean" case, not an error
    out=$(grep -nE "$DESTRUCTIVE_RE" "$f" || true)
    if [ -n "$out" ]; then
      printf '%s\n' "$out" | sed "s|^|${f##*/}: |"
      risky=0
    fi
  done
  return "$risky"
}
