import os
import sqlite3
import unittest
import uuid
from contextlib import closing, contextmanager
from unittest.mock import patch

import psycopg
from psycopg import sql

import database


@contextmanager
def isolated_database(with_facilities=False):
    url = os.environ.get("TEST_DATABASE_URL") or database.DATABASE_URL
    if not url:
        raise unittest.SkipTest("Set TEST_DATABASE_URL or DATABASE_URL for PostgreSQL tests")
    schema = "clinic_test_" + uuid.uuid4().hex
    with psycopg.connect(url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        with patch.object(database, "DATABASE_URL", url), patch.object(database, "DATABASE_SCHEMA", schema):
            database.initialize_database()
            if with_facilities:
                seed_facilities()
            yield schema
    finally:
        with psycopg.connect(url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def seed_facilities():
    from scripts.migrate_to_postgres import copy_table

    path = database.ROOT / "data/facilities.sqlite3"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with database.connect_database() as target:
            copy_table(source, target, "facilities", (
                "id", "type", "name", "address", "latitude", "longitude", "website", "open", "median_wait"),
                "SELECT id,type,name,address,latitude,longitude,website,open,median_wait FROM facilities "
                "WHERE address LIKE '宮崎県%' AND type IN ('hospital','clinic')")
            copy_table(source, target, "facility_departments", ("facility_id", "department"),
                "SELECT d.facility_id,d.department FROM facility_departments d JOIN facilities f ON f.id=d.facility_id "
                "WHERE f.address LIKE '宮崎県%' AND f.type IN ('hospital','clinic')")
