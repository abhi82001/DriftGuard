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
    headers = [(b"content-type", b"application/x-www-form-urlencoded")]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    scope = {"type": "http", "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": headers, "scheme": "http", "server": ("t", 80), "client": ("c", 1)}
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
