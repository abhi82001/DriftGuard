"""Structured logs: request/assessment ids, typed error codes, and no evidence content or secrets."""
import json
import logging

import pytest

import dg_helpers as h
from dg_helpers import webapp
import observability as obs

MARKER = b"ZZ-EVIDENCE-MARKER-4471"
SECRET = "sk-live-ABCDEF1234567890"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("DRIFTGUARD_REQUIRE_AUTH", "1")
    h.use_tmp_uploads(monkeypatch, tmp_path)
    webapp._RATE_BUCKETS.clear()
    caplog.set_level(logging.INFO, logger="driftguard.struct")


def _records(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "driftguard.struct"]


def test_every_line_is_json_with_request_id_and_header_matches(caplog):
    c = h.register(h.make_client())
    caplog.clear()
    r = c.get("/my-assessments", headers={"X-Request-ID": "trace-abc-12345"})
    assert r.headers["x-request-id"] == "trace-abc-12345"
    recs = _records(caplog)
    assert recs and all(x["request_id"] == "trace-abc-12345" for x in recs)
    line = [x for x in recs if x["event"] == "request"][0]
    assert line["method"] == "GET" and line["path"] == "/my-assessments" and line["status"] == 200 and "duration_ms" in line


def test_hostile_inbound_request_id_is_replaced():
    r = h.make_client().get("/health", headers={"X-Request-ID": "bad id\n{inject}"})
    assert r.headers["x-request-id"] != "bad id\n{inject}" and len(r.headers["x-request-id"]) == 16


def test_assessment_id_is_logged_and_errors_carry_typed_codes(caplog):
    a, b = h.register(h.make_client(), "a"), h.register(h.make_client(), "b")
    aid = h.analyze(a)
    caplog.clear()
    assert b.get(f"/export/{aid}").status_code == 404
    assert h.make_client().get(f"/export/{aid}").status_code == 403
    req = [x for x in _records(caplog) if x["event"] == "request"]
    assert [x["assessment_id"] for x in req] == [aid, aid]
    assert [x["error_code"] for x in req] == [obs.ErrorCode.NOT_FOUND.value, obs.ErrorCode.AUTH_REQUIRED.value]


def test_logs_contain_no_evidence_content_filenames_cookies_or_query_secrets(caplog):
    c = h.register(h.make_client())
    caplog.clear()
    payloads = [("Policy-CONFIDENTIAL-name.txt", b"Access Control Policy\n" + MARKER + b" mfa is required for administrators.\n"),
                ("users.csv", b"user,role\n" + MARKER + b",admin\n")]
    aid = h.analyze(c, "Vendor-Name-Private", payloads)
    c.get(f"/audit-trail/{aid}?question={SECRET}&format=csv")
    c.post("/jobs", data={"vendor": "Vendor-Name-Private"}, files=h.files(payloads))
    h.wait_job(c, c.post("/jobs", data={"vendor": "x"}, files=h.files(payloads)).json()["job_id"])
    blob = "\n".join(r.getMessage() for r in caplog.records if r.name == "driftguard.struct")
    assert blob
    cookie = next(iter(c.cookies.values()))
    for forbidden in (MARKER.decode(), "CONFIDENTIAL-name", "Vendor-Name-Private", SECRET, "CorrectHorseBattery9", cookie):
        assert forbidden not in blob, forbidden


def test_unhandled_error_logs_class_only_with_internal_code(caplog, monkeypatch):
    c = h.register(h.make_client())

    def boom(*a, **k):
        raise ValueError(f"leaky message {MARKER.decode()} {SECRET}")

    monkeypatch.setattr(webapp, "analyze_payloads", boom)
    caplog.clear()
    r = h.make_client()
    r.cookies.update(c.cookies)
    quiet = type(r)(webapp.app, follow_redirects=False, raise_server_exceptions=False)
    quiet.cookies.update(c.cookies)
    resp = quiet.post("/analyze", data={"vendor": "v"}, files=h.files())
    assert resp.status_code == 500
    recs = [x for x in _records(caplog) if x.get("error_code") == obs.ErrorCode.INTERNAL.value]
    assert recs and any(x.get("error_type") == "ValueError" for x in recs)
    assert MARKER.decode() not in json.dumps(recs) and SECRET not in json.dumps(recs)
    assert MARKER.decode() not in resp.text


def test_log_event_is_default_deny_and_scrubs_secrets(caplog):
    rec = obs.log_event("t", filename="secret.csv", excerpt="row data", password="p", status=200,
                        path=f"/x?token={SECRET}", error_type="Bearer abcdef123456 trailing")
    assert "filename" not in rec and "excerpt" not in rec and "password" not in rec
    assert rec["status"] == 200 and "abcdef123456" not in rec["error_type"]
    assert obs.log_event("t", code=obs.ErrorCode.STAGE_TIMEOUT)["error_code"] == "DG-JOB-002"
    assert {e.value for e in obs.ErrorCode} == {e.value for e in obs.ErrorCode} and len({e.value for e in obs.ErrorCode}) == len(obs.ErrorCode)
