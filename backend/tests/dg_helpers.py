"""Shared helpers for the run-record / isolation / job / logging tests."""
import itertools
import os
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("DRIFTGUARD_DB", str(Path(tempfile.mkdtemp()) / "records.db"))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

import app as webapp  # noqa: E402
from upload_store import UploadStore  # noqa: E402

_n = itertools.count(1)

PACK = [
    ("Access_Control_Policy.txt", b"Access Control Policy\n\nMulti-factor authentication is required for all employees and administrators "
     b"accessing production systems.\n\nUser access reviews are required quarterly and include employees, contractors.\n\n"
     b"Access is revoked within 24 hours of termination.\n"),
    ("users.csv", b"user,role,mfa_enabled\nalice,admin,true\nbob,user,false\n"),
]


def make_client():
    return TestClient(webapp.app, follow_redirects=False)


def register(client, prefix="u"):
    r = client.post("/register", data={"email": f"{prefix}{next(_n)}-{os.getpid()}@iso.test", "password": "CorrectHorseBattery9"})
    assert r.status_code == 303
    return client


def files(payloads=PACK):
    return [("files", (name, data)) for name, data in payloads]


def analyze(client, vendor="Acme Records", payloads=PACK):
    r = client.post("/analyze", data={"vendor": vendor}, files=files(payloads))
    assert r.status_code == 303, r.text
    return r.headers["location"].rsplit("/", 1)[-1]


def uid_of(client):
    return webapp._user_id(type("R", (), {"cookies": dict(client.cookies)})())


def wait_job(client, aid, states=("completed", "failed", "timed_out", "interrupted"), timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/jobs/{aid}").json()
        if st["state"] in states:
            return st
        time.sleep(0.05)
    raise AssertionError(f"job did not settle: {st}")


def use_tmp_uploads(monkeypatch, tmp_path):
    store = UploadStore(tmp_path / "uploads")
    monkeypatch.setattr(webapp, "UPLOADS", store)
    return store
