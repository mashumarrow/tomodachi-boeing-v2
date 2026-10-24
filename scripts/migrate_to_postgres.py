"""One-time, read-only import of legacy SQLite data into PostgreSQL."""

import argparse
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg import sql

from database import ROOT, connect_database, initialize_database


def copy_table(source, target, table, columns, select=None):
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
    count = 0
    with target.cursor() as cursor, cursor.copy(statement) as stream:
        for row in source.execute(select or f"SELECT {', '.join(columns)} FROM {table}"):
            stream.write_row(row)
            count += 1
    return count


def import_source(path, kind):
    if not path.is_file():
        raise ValueError(f"Source file not found: {path.name}")
    tables = ("facilities", "facility_departments") if kind == "facilities" else (
        "profiles", "visits", "reviews", "university_locations")
    marker = f"sqlite-{kind}-v1"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        source.execute("BEGIN")
        available = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = set(tables if kind == "facilities" else tables[:3])
        if not required.issubset(available):
            raise ValueError(f"Missing source tables: {kind}")
        with connect_database() as target:
            target.execute("SET LOCAL statement_timeout = '10min'")
            target.execute("SELECT pg_advisory_xact_lock(731944032)")
            if target.execute("SELECT 1 FROM data_imports WHERE kind = %s", (marker,)).fetchone():
                return {"skipped": True}
            target.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                sql.SQL(", ").join(map(sql.Identifier, tables))))
            for table in tables:
                if target.execute(sql.SQL("SELECT EXISTS(SELECT 1 FROM {})").format(sql.Identifier(table))).fetchone()[0]:
                    raise ValueError(f"Target {table} is not empty. Import refused to protect existing data.")
            counts = {}
            columns = {
                "facilities": ("id", "type", "name", "address", "latitude", "longitude", "website", "open", "median_wait"),
                "facility_departments": ("facility_id", "department"),
                "profiles": ("user_id", "payload"),
                "visits": ("user_id", "visit_id", "payload"),
                "reviews": ("user_id", "visit_id", "hospital_id", "payload", "review_order"),
                "university_locations": ("school_id", "address", "payload"),
            }
            for table in tables:
                if table in available:
                    select = "SELECT user_id, visit_id, hospital_id, payload, rowid FROM reviews ORDER BY rowid" if table == "reviews" else None
                    counts[table] = copy_table(source, target, table, columns[table], select)
            if kind == "records":
                target.execute("SELECT setval(pg_get_serial_sequence('reviews', 'review_order'), "
                               "COALESCE(MAX(review_order), 1), COUNT(*) > 0) FROM reviews")
            target.execute("INSERT INTO data_imports(kind) VALUES (%s)", (marker,))
            return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facilities", type=Path, default=ROOT / "data/facilities.sqlite3")
    parser.add_argument("--records", type=Path)
    parser.add_argument("--facilities-only", action="store_true")
    args = parser.parse_args()
    try:
        records = args.records or Path(os.environ.get("RECORDS_DATABASE", str(ROOT / "data/user-records.sqlite3")))
        if not args.facilities_only and (args.records is not None or os.environ.get("RECORDS_DATABASE")) and not records.is_file():
            raise ValueError(f"Source file not found: {records.name}")
        initialize_database()
        print("facilities:", import_source(args.facilities, "facilities"))
        if not args.facilities_only and records.is_file():
            print("records:", import_source(records, "records"))
        elif not args.facilities_only:
            print("No legacy records file; starting with empty records.")
    except ValueError as error:
        parser.exit(1, f"Migration stopped: {error}\n")
    except (psycopg.Error, sqlite3.Error):
        parser.exit(1, "Migration failed. Check DATABASE_URL, source schema and data validity. "
                    "The failed import was rolled back; SQLite files are unchanged.\n")


if __name__ == "__main__":
    main()
