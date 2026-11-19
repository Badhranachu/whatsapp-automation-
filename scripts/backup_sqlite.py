"""SQLite backup used by deploy.sh before applying migrations.

Runs inside a ONE-OFF backend container (never in the running one) that has:
  /data         the persistent volume with the live database
  /hostbackup   the host directory /var/backups/whatsapp-automation-bot (bind mount)

Usage (the script is fed on stdin):  python - <commit-sha> < scripts/backup_sqlite.py

It uses SQLite's online backup API, so the copy is consistent even while the application is running.
The backup is verified (integrity check) in BOTH locations. Only after a verified new backup exists are
old ones thinned out, keeping the 14 newest per location, so the only valid backup is never deleted.
"""
import datetime
import os
import shutil
import sqlite3
import sys

DB = '/data/db.sqlite3'
VOLUME_DIR = '/data/backups'
HOST_DIR = '/hostbackup'
KEEP = 14  # newest backups kept per location


def fail(message):
    print(f'BACKUP_FAILED: {message}', file=sys.stderr)
    sys.exit(1)


def verify(path):
    """The backup must open, pass SQLite's integrity check and contain tables."""
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
            tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        fail(f'cannot read backup {os.path.basename(path)}: {exc}')
    if integrity != 'ok' or tables < 1:
        fail(f'backup {os.path.basename(path)} failed verification (integrity={integrity}, tables={tables})')


def thin_out(directory):
    names = sorted(
        (n for n in os.listdir(directory) if n.startswith('db-') and n.endswith('.sqlite3')),
        reverse=True,  # timestamps in the names sort chronologically, newest first
    )
    for old in names[KEEP:]:
        os.remove(os.path.join(directory, old))


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isalnum():
        fail('usage: python - <commit-sha>')
    sha = sys.argv[1][:12]

    if not os.path.exists(DB):
        print('BACKUP_SKIPPED: no database file yet (first deployment), nothing to back up')
        return
    if not os.path.isdir(HOST_DIR):
        fail(f'{HOST_DIR} is not mounted, so the off-volume copy cannot be written')

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    name = f'db-{stamp}-{sha}.sqlite3'

    os.makedirs(VOLUME_DIR, exist_ok=True)
    volume_copy = os.path.join(VOLUME_DIR, name)
    source = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    target = sqlite3.connect(volume_copy)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    verify(volume_copy)

    host_copy = os.path.join(HOST_DIR, name)
    shutil.copy2(volume_copy, host_copy)
    verify(host_copy)

    # only now, with two verified copies in place, thin out the old ones
    thin_out(VOLUME_DIR)
    thin_out(HOST_DIR)
    print(f'BACKUP_OK {name}')


if __name__ == '__main__':
    main()
