"""Thread-safe SQLite connection pool using threading.local."""
import sqlite3
import threading
import os
from pathlib import Path

_local = threading.local()
DB_PATH = Path(__file__).parent.parent / "data" / "churn.db"


def get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    cur = conn.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def execute_write(sql: str, params: tuple = ()) -> int:
    conn = get_connection()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def init_db():
    schema_path = Path(__file__).parent / "schema.sql"
    conn = get_connection()
    conn.executescript(schema_path.read_text())
    conn.commit()
