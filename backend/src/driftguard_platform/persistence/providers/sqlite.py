from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires TEXT);
CREATE TABLE IF NOT EXISTS saved(user_id INTEGER, kind TEXT, aid TEXT, label TEXT,
created TEXT DEFAULT CURRENT_TIMESTAMP, blob TEXT, PRIMARY KEY(user_id, kind, aid));
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, action TEXT NOT NULL,
kind TEXT, aid TEXT, at TEXT NOT NULL, detail TEXT DEFAULT '');
"""

# Columns added after first release; applied additively so existing databases keep their rows.
_ADDED_COLUMNS = {"sessions": (("expires", "TEXT"),),
                  "saved": (("archived_at", "TEXT"), ("deleted_at", "TEXT"))}


class SQLiteStorageProvider:
    name = "sqlite"

    def __init__(self, database_url: str) -> None:
        raw = database_url or "driftguard.db"
        if raw.startswith("sqlite:///"):
            raw = raw[len("sqlite:///"):]
        self.path = str(Path(raw).expanduser())

    def _open(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.executescript(_SCHEMA)
        for table, columns in _ADDED_COLUMNS.items():
            have = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in have:
                    try:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                    except sqlite3.OperationalError as exc:
                        if "duplicate column" not in str(exc).lower():
                            raise  # only tolerate another connection adding it first
        return con

    def initialize(self) -> None:
        with self.connection():
            pass

    def connect(self) -> sqlite3.Connection:
        return self._open()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        con = self._open()
        try:
            yield con
        finally:
            con.close()

    def healthcheck(self) -> bool:
        try:
            with self.connection() as con:
                return con.execute("SELECT 1").fetchone() == (1,)
        except sqlite3.Error:
            return False
