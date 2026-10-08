from __future__ import annotations
import sqlite3
from ..accounts import AccountRepository, AuditEntry, DuplicateUserError, SavedAssessmentRow, retention_cutoff
from .sqlite import SQLiteStorageProvider

_SAVED_COLS = "kind, aid, label, created, archived_at, deleted_at"


def _audit(con, user_id, action, kind, aid, at, detail=""):
    con.execute("INSERT INTO audit_log(user_id,action,kind,aid,at,detail) VALUES(?,?,?,?,?,?)",
                (user_id, action, kind, aid, at, detail))


def _like(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _row(r) -> SavedAssessmentRow:
    return SavedAssessmentRow(str(r[0]), str(r[1]), str(r[2]), str(r[3]), r[4], r[5])


class SQLiteAccountRepository(AccountRepository):
    def __init__(self, storage: SQLiteStorageProvider) -> None:
        self.storage = storage

    def user_for_session(self, token, now_iso):
        with self.storage.connection() as con:
            row = con.execute("SELECT user_id FROM sessions WHERE token=? AND (expires IS NULL OR expires>?)", (token, now_iso)).fetchone()
        return row[0] if row else None

    # Soft-deleted rows are invisible to exists/load/previous, so they can never be opened.
    def saved_exists(self, user_id, kind, aid):
        with self.storage.connection() as con:
            return con.execute("SELECT 1 FROM saved WHERE user_id=? AND kind=? AND aid=? AND deleted_at IS NULL", (user_id, kind, aid)).fetchone() is not None

    def load_saved(self, user_id, kind, aid):
        with self.storage.connection() as con:
            row = con.execute("SELECT blob FROM saved WHERE user_id=? AND kind=? AND aid=? AND deleted_at IS NULL", (user_id, kind, aid)).fetchone()
        return row[0] if row else None

    def save_bounded(self, user_id, kind, aid, label, blob, limit=100):
        with self.storage.connection() as con, con:
            count = con.execute("SELECT COUNT(*) FROM saved WHERE user_id=?", (user_id,)).fetchone()[0]
            if count >= limit:
                con.execute("DELETE FROM saved WHERE rowid IN (SELECT rowid FROM saved WHERE user_id=? ORDER BY created ASC, rowid ASC LIMIT ?)", (user_id, count - limit + 1))
            # Upsert (not REPLACE) so a re-save keeps the user's rename and archive/delete state.
            con.execute("INSERT INTO saved(user_id,kind,aid,label,blob) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(user_id,kind,aid) DO UPDATE SET blob=excluded.blob", (user_id, kind, aid, label, blob))

    def previous_saved_blob(self, user_id, kind, aid, label):
        with self.storage.connection() as con:
            cur = con.execute("SELECT rowid FROM saved WHERE user_id=? AND kind=? AND aid=?", (user_id, kind, aid)).fetchone()
            row = con.execute(
                "SELECT blob FROM saved WHERE user_id=? AND kind=? AND aid!=? AND deleted_at IS NULL AND lower(label)=lower(?) AND rowid<? ORDER BY rowid DESC LIMIT 1",
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

    def list_saved(self, user_id, *, query="", kind="", date_from="", date_to="", archived=None, deleted=False):
        sql = [f"SELECT {_SAVED_COLS} FROM saved WHERE user_id=?"]
        args: list = [user_id]
        sql.append("AND deleted_at IS NOT NULL" if deleted else "AND deleted_at IS NULL")
        if query:
            sql.append("AND lower(label) LIKE ? ESCAPE '\\'")
            args.append(_like(query))
        if kind:
            sql.append("AND kind=?")
            args.append(kind)
        if date_from:
            sql.append("AND date(created)>=date(?)")
            args.append(date_from)
        if date_to:
            sql.append("AND date(created)<=date(?)")
            args.append(date_to)
        if archived is True:
            sql.append("AND archived_at IS NOT NULL")
        elif archived is False:
            sql.append("AND archived_at IS NULL")
        sql.append("ORDER BY deleted_at DESC, rowid DESC" if deleted else "ORDER BY created DESC, rowid DESC")
        with self.storage.connection() as con:
            rows = con.execute(" ".join(sql), args).fetchall()
        return tuple(_row(r) for r in rows)

    def get_saved_meta(self, user_id, kind, aid):
        with self.storage.connection() as con:
            r = con.execute(f"SELECT {_SAVED_COLS} FROM saved WHERE user_id=? AND kind=? AND aid=? AND deleted_at IS NULL",
                            (user_id, kind, aid)).fetchone()
        return _row(r) if r else None

    # --- lifecycle: every statement is scoped by user_id; a miss returns False (callers answer 404) ---
    def rename_saved(self, user_id, kind, aid, label, now_iso):
        with self.storage.connection() as con, con:
            old = con.execute("SELECT label FROM saved WHERE user_id=? AND kind=? AND aid=? AND deleted_at IS NULL",
                              (user_id, kind, aid)).fetchone()
            if old is None:
                return False
            con.execute("UPDATE saved SET label=? WHERE user_id=? AND kind=? AND aid=?", (label, user_id, kind, aid))
            _audit(con, user_id, "rename", kind, aid, now_iso, f"{old[0]} -> {label}")
            return True

    def _update(self, user_id, kind, aid, set_sql, params, where_extra, action, now_iso):
        with self.storage.connection() as con, con:
            cur = con.execute(f"UPDATE saved SET {set_sql} WHERE user_id=? AND kind=? AND aid=? AND {where_extra}",
                              (*params, user_id, kind, aid))
            if cur.rowcount != 1:
                return False
            _audit(con, user_id, action, kind, aid, now_iso)
            return True

    def set_archived(self, user_id, kind, aid, archived, now_iso):
        if archived:
            return self._update(user_id, kind, aid, "archived_at=COALESCE(archived_at, ?)", (now_iso,),
                                "deleted_at IS NULL", "archive", now_iso)
        return self._update(user_id, kind, aid, "archived_at=NULL", (), "deleted_at IS NULL", "unarchive", now_iso)

    def soft_delete_saved(self, user_id, kind, aid, now_iso):
        return self._update(user_id, kind, aid, "deleted_at=?", (now_iso,), "deleted_at IS NULL", "delete", now_iso)

    def restore_saved(self, user_id, kind, aid, now_iso, retention_days):
        """Only within the retention window; an expired-but-unpurged item can no longer be restored."""
        with self.storage.connection() as con, con:
            cur = con.execute("UPDATE saved SET deleted_at=NULL WHERE user_id=? AND kind=? AND aid=? "
                              "AND deleted_at IS NOT NULL AND deleted_at>?",
                              (user_id, kind, aid, retention_cutoff(now_iso, retention_days)))
            if cur.rowcount != 1:
                return False
            _audit(con, user_id, "restore", kind, aid, now_iso)
            return True

    def purge_saved(self, user_id, kind, aid, now_iso):
        """Permanently remove one of the owner's soft-deleted items, including its stored state/evidence blob."""
        with self.storage.connection() as con, con:
            cur = con.execute("DELETE FROM saved WHERE user_id=? AND kind=? AND aid=? AND deleted_at IS NOT NULL",
                              (user_id, kind, aid))
            if cur.rowcount != 1:
                return False
            _audit(con, user_id, "purge", kind, aid, now_iso, "owner requested")
            return True

    def purge_expired(self, now_iso, retention_days):
        cutoff = retention_cutoff(now_iso, retention_days)
        with self.storage.connection() as con, con:
            rows = con.execute("SELECT user_id, kind, aid FROM saved WHERE deleted_at IS NOT NULL AND deleted_at<=?",
                               (cutoff,)).fetchall()
            for uid, kind, aid in rows:
                con.execute("DELETE FROM saved WHERE user_id=? AND kind=? AND aid=?", (uid, kind, aid))
                _audit(con, uid, "purge", kind, aid, now_iso, f"retention {int(retention_days)}d expired")
        return tuple((int(u), str(k), str(a)) for u, k, a in rows)

    def record_audit(self, user_id, action, kind, aid, now_iso, detail=""):
        with self.storage.connection() as con, con:
            _audit(con, user_id, action, kind, aid, now_iso, detail)

    def list_audit(self, user_id, limit=20):
        with self.storage.connection() as con:
            rows = con.execute("SELECT user_id, action, kind, aid, at, detail FROM audit_log WHERE user_id=? "
                               "ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
        return tuple(AuditEntry(int(u), str(a), str(k or ""), str(i or ""), str(t), str(d or "")) for u, a, k, i, t, d in rows)
