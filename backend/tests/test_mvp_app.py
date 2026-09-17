#!/usr/bin/env python3
"""MVP smoke tests: app starts, questionnaire loads, demo assessment runs
offline, results render, provider failure degrades to NEEDS_REVIEW.

No network call and no HTTP client dependency: the ASGI app is called directly.
"""

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

import app as webapp  # noqa: E402
from assessment import (  # noqa: E402
    STATUS_NEEDS_REVIEW,
    MvpKnowledge,
    run_assessment,
)

Q_SEM = "QN-ACCESS-001-Q09"
Q_DET = "QN-ACCESS-001-Q01"
QN = "QN-ACCESS-001"
ANSWER = "Primary database and its snapshots are encrypted with KMS keys."


def _call(method: str, path: str, form: dict | None = None,
          body: bytes | None = None, content_type: str | None = None):
    if body is None:
        body = urlencode(form or {}, doseq=True).encode() if form else b""
        content_type = content_type or (
            "application/x-www-form-urlencoded" if form else None
        )
    headers = [(b"host", b"test")]
    if content_type:
        headers.append((b"content-type", content_type.encode()))
    headers.append((b"content-length", str(len(body)).encode()))
    query = b""
    if "?" in path:
        path, _, q = path.partition("?")
        query = q.encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": query,
        "root_path": "", "headers": headers, "client": ("test", 1),
        "server": ("test", 80),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(webapp.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    text = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    ).decode("utf-8")
    location = dict(start["headers"]).get(b"location", b"").decode()
    return start["status"], text, location


# ---------------------------------------------------------------------- 1
def test_1_app_starts_and_landing_page_renders():
    status, text, _ = _call("GET", "/")
    assert status == 200
    assert "DriftGuard" in text
    assert "Analyze Documents" in text
    assert "Start Manual Assessment" in text
    assert "MODE: DEMO" in text


# ---------------------------------------------------------------------- 2
def test_2_questionnaire_loads():
    status, text, _ = _call("POST", "/assessment", {"vendor": "Acme Cloud Inc."})
    assert status == 200
    assert "Acme Cloud Inc." in text
    assert "Run Assessment" in text
    assert Q_DET in text and Q_SEM in text
    assert "QN-OPS-001" in text          # CC7 questionnaire present


# ---------------------------------------------------------------------- 3
def test_3_demo_assessment_runs_without_network():
    status, _, location = _call("POST", "/run", {
        "vendor": "Acme Cloud Inc.",
        f"{QN}|{Q_DET}": "No",
        f"{QN}|{Q_SEM}": ANSWER,
    })
    assert status == 303
    assert location.startswith("/results/")

    assessment = webapp.ASSESSMENTS[location.rsplit("/", 1)[1]]
    assert assessment.mode == "DEMO"
    by_id = {r.question_id: r for r in assessment.results}

    det = by_id[Q_DET]
    assert det.mode == "deterministic"
    assert det.findings and det.findings[0]["finding_id"].startswith("FND-")
    assert det.findings[0]["remediations"]          # mapped from knowledge only

    sem = by_id[Q_SEM]
    assert sem.mode == "semantic"
    assert sem.verdict in {"SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT",
                           "UNDETERMINED"}
    assert sem.needs_review is True
    assert sem.source == "demo-stub"


# ---------------------------------------------------------------------- 4
def test_4_results_page_renders():
    _, _, location = _call("POST", "/run", {
        "vendor": "Acme Cloud Inc.",
        f"{QN}|{Q_DET}": "No",
        f"{QN}|{Q_SEM}": ANSWER,
    })
    status, text, _ = _call("GET", location)
    assert status == 200
    for expected in ("Acme Cloud Inc.", "MODE: DEMO", Q_DET, Q_SEM,
                     "Evaluated questions", "NEEDS REVIEW", "DEMO"):
        assert expected in text, expected
    assert "not an audit opinion" in text.lower()


# ---------------------------------------------------------------------- 5
def test_5_provider_failure_becomes_needs_review():
    knowledge = MvpKnowledge()

    # No model / SDK / key configured: real-mode semantic items degrade safely.
    saved = os.environ.pop("DRIFTGUARD_CLAUDE_MODEL", None)
    try:
        assessment = run_assessment(
            knowledge, "Acme Cloud Inc.",
            {(QN, Q_DET): "No", (QN, Q_SEM): ANSWER},
            demo=False,
        )
    finally:
        if saved is not None:
            os.environ["DRIFTGUARD_CLAUDE_MODEL"] = saved

    by_id = {r.question_id: r for r in assessment.results}
    sem = by_id[Q_SEM]
    assert sem.status == STATUS_NEEDS_REVIEW
    assert sem.needs_review is True
    assert sem.detail                                   # useful message
    assert not sem.findings                             # nothing invented
    # The deterministic half of the assessment still completed.
    assert by_id[Q_DET].findings


TESTS = [
    test_1_app_starts_and_landing_page_renders,
    test_2_questionnaire_loads,
    test_3_demo_assessment_runs_without_network,
    test_4_results_page_renders,
    test_5_provider_failure_becomes_needs_review,
]


def run() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  ok    {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if failed else 'PASSED'}: {failed} failure(s)")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
