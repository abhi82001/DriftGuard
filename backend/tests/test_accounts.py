"""Accounts + persistence: password hashing, and a saved assessment survives a store reset."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"
os.environ["DRIFTGUARD_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")

import app as webapp  # noqa: E402


def _call(method, path, body=b"", cookie=""):
    out = {}
    path, _, query = path.partition("?")
    headers = [(b"content-type", b"application/x-www-form-urlencoded")]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    scope = {"type": "http", "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": query.encode(), "headers": headers, "scheme": "http", "server": ("t", 80), "client": ("c", 1)}
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    chunks = []

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
            out["headers"] = {k.decode().lower(): v.decode() for k, v in msg["headers"]}
        else:
            chunks.append(msg.get("body", b""))

    asyncio.run(webapp.app(scope, receive, send))
    out["body"] = b"".join(chunks).decode()
    return out


def test_password_is_hashed_and_verified():
    h = webapp._hash_pw("s3cret-pass")
    assert "s3cret-pass" not in h
    assert webapp._check_pw("s3cret-pass", h) and not webapp._check_pw("wrong", h)


def test_what_changed_card_on_second_run_for_same_company():
    r = _call("POST", "/register", urlencode({"email": "wc@b.co", "password": "longenough1"}).encode())
    cookie = r["headers"]["set-cookie"].split(";")[0]
    first = _call("POST", "/analyze-sample", cookie=cookie)["headers"]["location"]
    assert "What changed" not in _call("GET", first, cookie=cookie)["body"]
    second = _call("POST", "/analyze-sample", cookie=cookie)["headers"]["location"]
    body = _call("GET", second, cookie=cookie)["body"]
    assert "What changed" in body and "Improved" in body and "Regressed" in body and "Still open" in body


def test_saved_assessment_reopens_after_store_reset():
    r = _call("POST", "/register", urlencode({"email": "a@b.co", "password": "longenough1"}).encode())
    assert r["status"] == 303
    cookie = r["headers"]["set-cookie"].split(";")[0]
    loc = _call("POST", "/analyze-sample", cookie=cookie)["headers"]["location"]
    assert "/doc-results/" in loc
    assert webapp.DOC_ASSESSMENTS.pop(loc.rsplit("/", 1)[1]) is not None
    assert _call("GET", loc, cookie=cookie)["status"] == 200
    assert loc in _call("GET", "/my-assessments", cookie=cookie)["body"]
    assert _call("GET", "/my-assessments")["status"] == 303


# ---- saved-assessment lifecycle (rename/archive/delete/restore/purge/search/compare) ----
import re as _re  # noqa: E402
import pytest  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

_n = [0]


def _user():
    _n[0] += 1
    r = _call("POST", "/register", urlencode({"email": f"lc{_n[0]}@b.co", "password": "longenough1"}).encode())
    return r["headers"]["set-cookie"].split(";")[0]


def _uid(cookie):
    return webapp._accounts().user_for_session(cookie.split("=", 1)[1], "0000")


def _sample(cookie):
    loc = _call("POST", "/analyze-sample", cookie=cookie)["headers"]["location"]
    kind, aid = _re.match(r"^/([^/]+)/([^/?#]+)", loc).groups()
    return loc, kind, aid


def _act(cookie, action, kind, aid, **extra):
    return _call("POST", f"/my-assessments/{action}", urlencode({"kind": kind, "aid": aid, **extra}).encode(), cookie=cookie)


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_REQUIRE_AUTH", "1")  # conftest defaults it off


def _iso(delta_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat()


def test_other_user_cannot_touch_items_and_denials_are_audited(auth_on):
    a, b = _user(), _user()
    loc, kind, aid = _sample(a)
    for action in ("rename", "archive", "unarchive", "delete", "restore", "purge"):
        assert _act(b, action, kind, aid, label="x")["status"] == 404, action
    assert webapp._accounts().load_saved(_uid(a), kind, aid) is not None  # untouched
    assert [r.label for r in webapp._accounts().list_saved(_uid(a))] != ["x"]
    assert _call("GET", loc, cookie=a)["status"] == 200
    assert _call("GET", loc, cookie=b)["status"] == 404
    denied = [e.action for e in webapp._accounts().list_audit(_uid(b), 20)]
    assert "delete.denied" in denied and "purge.denied" in denied
    mine = _sample(b)
    assert _call("GET", f"/my-assessments/compare?pick={kind}:{aid}&pick={mine[1]}:{mine[2]}", cookie=b)["status"] == 404
    assert _call("POST", "/my-assessments/delete", urlencode({"kind": kind, "aid": aid}).encode())["status"] == 303  # anon -> login
    assert webapp._accounts().load_saved(_uid(a), kind, aid) is not None


def test_rename_archive_delete_restore_and_audit(auth_on):
    c = _user()
    uid = _uid(c)
    loc, kind, aid = _sample(c)
    assert _act(c, "rename", kind, aid, label="  Renamed   Co ")["status"] == 303
    assert _act(c, "rename", kind, aid, label="  ")["status"] == 400
    assert [r.label for r in webapp._accounts().list_saved(uid)] == ["Renamed Co"]
    assert "Renamed Co" in _call("GET", "/my-assessments", cookie=c)["body"]
    _act(c, "archive", kind, aid)
    assert "Renamed Co" not in _call("GET", "/my-assessments", cookie=c)["body"].split("Recent activity")[0]
    assert "Renamed Co" in _call("GET", "/my-assessments?archived=archived", cookie=c)["body"]
    assert _call("GET", loc, cookie=c)["status"] == 200  # archived items still open
    _act(c, "unarchive", kind, aid)
    assert _act(c, "delete", kind, aid)["status"] == 303
    assert _call("GET", loc, cookie=c)["status"] == 404  # cannot be opened
    assert "Renamed Co" not in _call("GET", "/my-assessments?archived=all", cookie=c)["body"].split("Recent activity")[0]
    assert "Renamed Co" in _call("GET", "/my-assessments?view=trash", cookie=c)["body"]
    assert _act(c, "delete", kind, aid)["status"] == 404  # already deleted
    assert _act(c, "rename", kind, aid, label="y")["status"] == 404
    assert _act(c, "restore", kind, aid)["status"] == 303
    assert _call("GET", loc, cookie=c)["status"] == 200
    assert [r.label for r in webapp._accounts().list_saved(uid)] == ["Renamed Co"]  # name survives
    audit = webapp._accounts().list_audit(uid, 50)
    for expected in ("rename", "archive", "unarchive", "delete", "restore"):
        assert expected in [e.action for e in audit]
    assert all(e.user_id == uid and e.at for e in audit)


def test_retention_window_and_purge_removes_stored_state(auth_on):
    repo = webapp._accounts()
    c = _user()
    uid = _uid(c)
    _, kind, aid = _sample(c)
    _, kind2, aid2 = _sample(c)
    repo.soft_delete_saved(uid, kind, aid, _iso(-10))
    repo.soft_delete_saved(uid, kind2, aid2, _iso(-1))
    assert repo.purge_expired(_iso(), 30) == ()                      # inside the window
    assert repo.restore_saved(uid, kind2, aid2, _iso(), 30) is True  # restorable
    repo.soft_delete_saved(uid, kind2, aid2, _iso(-1))
    assert repo.restore_saved(uid, kind, aid, _iso(), 5) is False    # window passed, not yet purged
    assert repo.purge_expired(_iso(), 5) == ((uid, kind, aid),)
    with repo.storage.connection() as con:
        assert con.execute("SELECT COUNT(*) FROM saved WHERE user_id=? AND aid=?", (uid, aid)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM saved WHERE user_id=? AND aid=?", (uid, aid2)).fetchone()[0] == 1
    assert repo.restore_saved(uid, kind, aid, _iso(), 365) is False  # gone for good
    assert "purge" in [e.action for e in repo.list_audit(uid, 50)]
    # owner-requested purge only applies to already-deleted items, and evicts in-memory state
    _, k3, a3 = _sample(c)
    assert _act(c, "purge", k3, a3)["status"] == 404
    _act(c, "delete", k3, a3)
    assert _act(c, "purge", k3, a3)["status"] == 303
    assert webapp._STORES[k3].get(a3) is None and (k3, a3) not in webapp._ASSESSMENT_OWNERS
    assert repo.load_saved(uid, k3, a3) is None


def test_retention_days_is_configurable_and_list_view_purges_expired():
    c = _user()
    uid = _uid(c)
    _, kind, aid = _sample(c)
    _act(c, "delete", kind, aid)
    _call("GET", "/my-assessments", cookie=c)
    assert len(webapp._accounts().list_saved(uid, deleted=True)) == 1  # default 30 days keeps it
    os.environ["DRIFTGUARD_RETENTION_DAYS"] = "0"
    try:
        assert webapp._retention_days() == 0
        _call("GET", "/my-assessments", cookie=c)
    finally:
        del os.environ["DRIFTGUARD_RETENTION_DAYS"]
    assert webapp._retention_days() == 30
    assert webapp._accounts().list_saved(uid, deleted=True) == ()


def test_search_filter_by_name_kind_date_archived_and_escaping():
    repo = webapp._accounts()
    c = _user()
    uid = _uid(c)
    repo.save_bounded(uid, "doc-results", "s1", "Acme Corp", "{}")
    repo.save_bounded(uid, "results", "s2", "Beta_100%", "{}")
    repo.save_bounded(uid, "doc-results", "s3", "Gamma", "{}")
    repo.set_archived(uid, "doc-results", "s3", True, _iso())

    def names(**kw):
        return sorted(r.label for r in repo.list_saved(uid, **kw))

    assert names(query="acme") == ["Acme Corp"]
    assert names(query="_1") == ["Beta_100%"] and names(query="%") == ["Beta_100%"]
    assert names(query="a_m") == []  # wildcards are literal
    assert names(kind="results") == ["Beta_100%"]
    assert names(archived=True) == ["Gamma"] and names(archived=False) == ["Acme Corp", "Beta_100%"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert len(names(date_from=today, date_to=today)) == 3
    assert names(date_to="2000-01-01") == [] and names(date_from="2999-01-01") == []
    page = _call("GET", "/my-assessments?q=acme&kind=doc-results", cookie=c)["body"]
    assert "Acme Corp" in page and "Beta_100" not in page
    assert "Nothing matches" in _call("GET", "/my-assessments?q=zzz", cookie=c)["body"]


def test_compare_counts_status_changes_with_provenance_and_no_verdict_words():
    from assessment_compare import CompareUnsupported, compare_assessments
    from documents import AreaResult, DocumentAssessment

    def area(qid, status, f="a.xlsx", loc="Sheet1!B2"):
        return AreaResult("Q", qid, f"Area {qid}", "q?", status, "r", f, loc, "snippet")

    def doc(aid, *areas):
        return DocumentAssessment(aid, "Acme", "DEMO", [], [], list(areas))

    base = doc("1", area("Q01", "PARTIAL"), area("Q02", "ESTABLISHED"), area("Q03", "NOT_EVALUATED"))
    other = doc("2", area("Q01", "ESTABLISHED", "b.xlsx", "Sheet2!C3"), area("Q02", "ESTABLISHED"), area("Q04", "PARTIAL"))
    cmp = compare_assessments(base, other)
    assert cmp.base_counts == {"PARTIAL": 1, "ESTABLISHED": 1, "NOT_EVALUATED": 1}
    assert cmp.other_counts == {"ESTABLISHED": 2, "PARTIAL": 1}
    by = {c.question_id: c for c in cmp.changes}
    assert [by[q].change for q in ("Q01", "Q02", "Q03", "Q04")] == ["CHANGED", "UNCHANGED", "REMOVED", "ADDED"]
    assert (by["Q01"].base.source_file, by["Q01"].base.source_locator) == ("a.xlsx", "Sheet1!B2")
    assert (by["Q01"].other.source_file, by["Q01"].other.source_locator) == ("b.xlsx", "Sheet2!C3")
    assert cmp.unchanged == 1
    with pytest.raises(CompareUnsupported):
        compare_assessments(object(), other)

    # end to end: owner sees both runs' counts; the page carries no verdict words
    c = _user()
    _, k1, a1 = _sample(c)
    _, k2, a2 = _sample(c)
    page = _call("GET", f"/my-assessments/compare?pick={k1}:{a1}&pick={k2}:{a2}", cookie=c)
    assert page["status"] == 200 and "Counts by status" in page["body"] and "Question changes" in page["body"]
    for word in ("COMPLIANT", "PASS", "FAIL", "CERTIFIED", "AUDIT_OPINION"):
        assert word not in page["body"].upper().replace("PASSWORD", "")
    assert "compare" in [e.action for e in webapp._accounts().list_audit(_uid(c), 50)]
    assert _call("GET", f"/my-assessments/compare?pick={k1}:{a1}", cookie=c)["status"] == 400


def test_existing_database_is_migrated_additively():
    import sqlite3
    from driftguard_platform.persistence.providers.sqlite import SQLiteStorageProvider
    from driftguard_platform.persistence.providers.sqlite_accounts import SQLiteAccountRepository
    path = Path(tempfile.mkdtemp()) / "old.db"
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE saved(user_id INTEGER, kind TEXT, aid TEXT, label TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP,"
                      " blob TEXT, PRIMARY KEY(user_id, kind, aid));"
                      "INSERT INTO saved(user_id,kind,aid,label,blob) VALUES(1,'doc-results','old','Legacy','{}');")
    con.commit()
    con.close()
    repo = SQLiteAccountRepository(SQLiteStorageProvider(str(path)))
    repo.storage.initialize()
    repo.storage.initialize()  # idempotent
    assert [(r.label, r.archived_at, r.deleted_at) for r in repo.list_saved(1)] == [("Legacy", None, None)]
    assert repo.soft_delete_saved(1, "doc-results", "old", _iso()) and repo.list_saved(1) == ()
