"""Tests for scripts/backup_sqlite.py using real SQLite files in temporary folders.

    python scripts/test_backup_sqlite.py
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).with_name('backup_sqlite.py')
SHA = '0123456789abcdef0123456789abcdef01234567'


def load_script():
    spec = importlib.util.spec_from_file_location('backup_sqlite', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.db = root / 'data' / 'db.sqlite3'
        self.volume = root / 'data' / 'backups'
        self.host = root / 'hostbackup'
        self.db.parent.mkdir()
        self.host.mkdir()
        self.mod = load_script()
        self.mod.DB, self.mod.VOLUME_DIR, self.mod.HOST_DIR = str(self.db), str(self.volume), str(self.host)

    def make_db(self, rows=5):
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, name TEXT)')
        conn.executemany('INSERT INTO django_migrations (name) VALUES (?)', [(f'm{i}',) for i in range(rows)])
        conn.commit()
        conn.close()

    def run_main(self, sha=SHA):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with patch.object(sys, 'argv', ['backup_sqlite.py', sha]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.mod.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def names(self, folder):
        return sorted(p.name for p in pathlib.Path(folder).glob('db-*.sqlite3'))

    def test_creates_a_verified_backup_in_both_places(self):
        self.make_db(7)
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn('BACKUP_OK', out)
        for folder in (self.volume, self.host):
            files = self.names(folder)
            self.assertEqual(len(files), 1)
            self.assertRegex(files[0], r'^db-\d{8}T\d{6}Z-0123456789ab\.sqlite3$')  # timestamp + 12-char commit SHA
            conn = sqlite3.connect(pathlib.Path(folder) / files[0])
            self.assertEqual(conn.execute('SELECT count(*) FROM django_migrations').fetchone()[0], 7)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            conn.close()

    def test_the_live_database_is_not_modified(self):
        self.make_db(3)
        before = self.db.read_bytes()
        self.run_main()
        self.assertEqual(self.db.read_bytes(), before)

    def test_no_database_yet_means_nothing_to_back_up(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn('BACKUP_SKIPPED', out)
        self.assertEqual(self.names(self.host), [])

    def test_missing_host_directory_fails_before_anything_is_written(self):
        self.make_db()
        self.host.rmdir()
        code, _, err = self.run_main()
        self.assertNotEqual(code, 0)
        self.assertIn('BACKUP_FAILED', err)
        self.assertFalse(self.volume.exists())  # nothing was written anywhere

    def test_retention_keeps_the_14_newest_and_never_the_only_backup(self):
        self.make_db()
        for folder in (self.volume, self.host):
            pathlib.Path(folder).mkdir(parents=True, exist_ok=True)
            for day in range(1, 21):  # 20 old backups
                sqlite3.connect(pathlib.Path(folder) / f'db-202001{day:02d}T000000Z-aaaaaaaaaaaa.sqlite3').close()
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        for folder in (self.volume, self.host):
            files = self.names(folder)
            self.assertEqual(len(files), 14)
            self.assertTrue(any('0123456789ab' in f for f in files), 'the new backup must be kept')
            self.assertNotIn('db-20200101T000000Z-aaaaaaaaaaaa.sqlite3', files)  # the oldest went first
            self.assertIn('db-20200120T000000Z-aaaaaaaaaaaa.sqlite3', files)

    def test_unrelated_files_in_the_backup_folders_are_never_deleted(self):
        self.make_db()
        self.volume.mkdir(parents=True)
        (self.host / 'notes.txt').write_text('keep me')
        (self.volume / 'other.sqlite3').write_text('keep me too')
        self.run_main()
        self.assertTrue((self.host / 'notes.txt').exists())
        self.assertTrue((self.volume / 'other.sqlite3').exists())

    def test_verification_rejects_a_corrupt_file(self):
        bad = pathlib.Path(self.tmp.name) / 'bad.sqlite3'
        bad.write_bytes(os.urandom(4096))
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
            self.mod.verify(str(bad))
        self.assertNotEqual(ctx.exception.code, 0)

    def test_verification_rejects_an_empty_database(self):
        empty = pathlib.Path(self.tmp.name) / 'empty.sqlite3'
        sqlite3.connect(empty).close()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.mod.verify(str(empty))

    def test_bad_arguments_are_rejected(self):
        self.make_db()
        for bad in ('', 'abc; rm -rf /', '../x'):
            code, _, err = self.run_main(bad)
            self.assertNotEqual(code, 0, bad)
        self.assertEqual(self.names(self.host), [])

    def test_two_backups_in_a_row_both_survive(self):
        self.make_db()
        self.run_main('a' * 40)
        import time
        time.sleep(1.1)  # names carry a one-second timestamp
        self.run_main('b' * 40)
        self.assertEqual(len(self.names(self.host)), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
