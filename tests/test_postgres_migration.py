import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

import psycopg

from database import connect_database
from scripts.migrate_to_postgres import import_source, main
from tests.db_support import isolated_database


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        context = isolated_database()
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.path = Path(self.directory.name) / "records.sqlite3"
        with closing(sqlite3.connect(self.path)) as source, source:
            source.executescript("""
                CREATE TABLE profiles(user_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE visits(user_id TEXT, visit_id TEXT, payload TEXT);
                CREATE TABLE reviews(user_id TEXT, visit_id TEXT, hospital_id TEXT, payload TEXT);
                CREATE TABLE university_locations(school_id TEXT, address TEXT, payload TEXT);
            """)
            source.execute("INSERT INTO profiles VALUES (?, ?)", ("owner", json.dumps({"nickname": "Student"})))
            source.execute("INSERT INTO visits VALUES (?, ?, ?)", ("owner", "first", json.dumps({"arrivalAt": "2026-10-01T01:00:00Z", "stayMinutes": 35})))
            for visit in ("first", "second"):
                source.execute("INSERT INTO reviews VALUES (?, ?, ?, ?)",
                    ("owner", visit, "clinic:stable", json.dumps({"id": visit, "universityEmailVerified": True})))
            source.execute("INSERT INTO university_locations VALUES (?, ?, ?)", ("school", "address", '{"latitude":31}'))

    def test_import_preserves_payloads_order_sequence_and_readonly_source(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        self.assertEqual(import_source(self.path, "records"), {
            "profiles": 1, "visits": 1, "reviews": 2, "university_locations": 1})
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)
        with closing(sqlite3.connect(self.path)) as source, connect_database() as target:
            for table, columns in (("profiles", "user_id,payload"), ("visits", "user_id,visit_id,payload"),
                                   ("reviews", "user_id,visit_id,hospital_id,payload"),
                                   ("university_locations", "school_id,address,payload")):
                self.assertEqual(sorted(source.execute(f"SELECT {columns} FROM {table}").fetchall()),
                                 sorted(target.execute(f"SELECT {columns} FROM {table}").fetchall()))
            self.assertEqual(target.execute("SELECT visit_id FROM reviews ORDER BY review_order DESC").fetchall(),
                             [("second",), ("first",)])
            order = target.execute("INSERT INTO reviews(user_id,visit_id,hospital_id,payload) "
                                   "VALUES ('owner','third','clinic:stable','{}') RETURNING review_order").fetchone()[0]
            self.assertGreater(order, 2)

    def test_rerun_cannot_restore_deleted_accounts_or_overwrite_new_data(self):
        import_source(self.path, "records")
        with connect_database() as target:
            for table in ("profiles", "visits", "reviews"):
                target.execute(f"DELETE FROM {table}")
            target.execute("INSERT INTO profiles VALUES ('new-user', '{}')")
        self.assertEqual(import_source(self.path, "records"), {"skipped": True})
        with connect_database() as target:
            self.assertEqual(target.execute("SELECT user_id FROM profiles").fetchall(), [("new-user",)])
            self.assertEqual(target.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 0)

    def test_invalid_json_rolls_back_all_tables_and_marker(self):
        with closing(sqlite3.connect(self.path)) as source, source:
            source.execute("UPDATE reviews SET payload = 'not json' WHERE visit_id = 'second'")
        with self.assertRaises(psycopg.Error):
            import_source(self.path, "records")
        with connect_database() as target:
            for table in ("profiles", "visits", "reviews", "data_imports"):
                self.assertEqual(target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_unmarked_nonempty_target_is_protected(self):
        with connect_database() as target:
            target.execute("INSERT INTO profiles VALUES ('existing', '{}')")
        with self.assertRaises(ValueError):
            import_source(self.path, "records")
        with connect_database() as target:
            self.assertEqual(target.execute("SELECT user_id FROM profiles").fetchall(), [("existing",)])

    def test_explicit_missing_records_path_fails_before_any_import(self):
        with patch("sys.argv", ["migrate", "--records", str(Path(self.directory.name) / "missing.sqlite3")]), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        with connect_database() as target:
            self.assertEqual(target.execute("SELECT COUNT(*) FROM data_imports").fetchone()[0], 0)

    def test_facilities_import_and_idempotence(self):
        path = Path(self.directory.name) / "facilities.sqlite3"
        with closing(sqlite3.connect(path)) as source, source:
            source.executescript("""
                CREATE TABLE facilities(id,type,name,address,latitude,longitude,website,open,median_wait);
                CREATE TABLE facility_departments(facility_id,department);
                INSERT INTO facilities VALUES ('clinic:stable','clinic','Clinic','Miyazaki',31,131,'','',35);
                INSERT INTO facility_departments VALUES ('clinic:stable','internal');
            """)
        self.assertEqual(import_source(path, "facilities"), {"facilities": 1, "facility_departments": 1})
        self.assertEqual(import_source(path, "facilities"), {"skipped": True})
        with connect_database() as target:
            self.assertEqual(target.execute("SELECT id FROM facilities").fetchall(), [("clinic:stable",)])
