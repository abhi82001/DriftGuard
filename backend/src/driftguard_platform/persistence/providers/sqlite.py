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
"""


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
        cols = {row[1] for row in con.execute("PRAGMA table_info(sessions)")}
        if "expires" not in cols:
            con.execute("ALTER TABLE sessions ADD COLUMN expires TEXT")
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
