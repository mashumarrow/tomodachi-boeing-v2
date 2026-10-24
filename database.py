import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DATABASE_SCHEMA = os.environ.get("DATABASE_SCHEMA", "public").strip()


@contextmanager
def connect_database():
    if not DATABASE_URL:
        raise psycopg.OperationalError("DATABASE_URL is not configured. Set a PostgreSQL connection URL.")
    with psycopg.connect(DATABASE_URL, connect_timeout=10) as connection:
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(DATABASE_SCHEMA)))
        connection.execute("SET LOCAL statement_timeout = '30s'")
        yield connection


def initialize_database():
    with connect_database() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(731944031)")
        connection.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))


def lock_user(connection, subject):
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (subject,))
