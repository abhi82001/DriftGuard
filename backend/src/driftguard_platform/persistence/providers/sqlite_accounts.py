from __future__ import annotations
import sqlite3
from ..accounts import AccountRepository, DuplicateUserError, SavedAssessmentRow
from .sqlite import SQLiteStorageProvider


class SQLiteAccountRepository(AccountRepository):
    def __init__(self, storage: SQLiteStorageProvider) -> None:
        self.storage = storage

    def user_for_session(self, token, now_iso):
        with self.storage.connection() as con:
            row = con.execute("SELECT user_id FROM sessions WHERE token=? AND (expires IS NULL OR expires>?)", (token, now_iso)).fetchone()
        return row[0] if row else None

    def saved_exists(self, user_id, kind, aid):
        with self.storage.connection() as con:
            return con.execute("SELECT 1 FROM saved WHERE user_id=? AND kind=? AND aid=?", (user_id, kind, aid)).fetchone() is not None

    def load_saved(self, user_id, kind, aid):
        with self.storage.connection() as con:
            row = con.execute("SELECT blob FROM saved WHERE user_id=? AND kind=? AND aid=?", (user_id, kind, aid)).fetchone()
        return row[0] if row else None

    def save_bounded(self, user_id, kind, aid, label, blob, limit=100):
        with self.storage.connection() as con, con:
            count = con.execute("SELECT COUNT(*) FROM saved WHERE user_id=?", (user_id,)).fetchone()[0]
            if count >= limit:
                con.execute("DELETE FROM saved WHERE rowid IN (SELECT rowid FROM saved WHERE user_id=? ORDER BY created ASC, rowid ASC LIMIT ?)", (user_id, count - limit + 1))
            con.execute("INSERT OR REPLACE INTO saved(user_id,kind,aid,label,blob) VALUES(?,?,?,?,?)", (user_id, kind, aid, label, blob))

    def previous_saved_blob(self, user_id, kind, aid, label):
        with self.storage.connection() as con:
            cur = con.execute("SELECT rowid FROM saved WHERE user_id=? AND kind=? AND aid=?", (user_id, kind, aid)).fetchone()
            row = con.execute(
                "SELECT blob FROM saved WHERE user_id=? AND kind=? AND aid!=? AND lower(label)=lower(?) AND rowid<? ORDER BY rowid DESC LIMIT 1",
                (user_id, kind, aid, label, cur[0] if cur else 0),
            ).fetchone()
        return row[0] if row else None

    def create_user(self, email, password_hash):
        try:
            with self.storage.connection() as con, con:
                return int(con.execute("INSERT INTO users(email,pw) VALUES(?,?)", (email, password_hash)).lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DuplicateUserError(email) from exc

    def find_user(self, email):
        with self.storage.connection() as con:
            row = con.execute("SELECT id, pw FROM users WHERE email=?", (email,)).fetchone()
        return (int(row[0]), str(row[1])) if row else None

    def update_password(self, user_id, password_hash):
        with self.storage.connection() as con, con:
            con.execute("UPDATE users SET pw=? WHERE id=?", (password_hash, user_id))

    def replace_session(self, user_id, token, expires):
        with self.storage.connection() as con, con:
            con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            con.execute("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)", (token, user_id, expires))

    def delete_session(self, token):
        with self.storage.connection() as con, con:
            con.execute("DELETE FROM sessions WHERE token=?", (token,))

    def list_saved(self, user_id):
        with self.storage.connection() as con:
            rows = con.execute("SELECT kind, aid, label, created FROM saved WHERE user_id=? ORDER BY created DESC", (user_id,)).fetchall()
        return tuple(SavedAssessmentRow(str(k), str(a), str(label), str(created)) for k, a, label, created in rows)
