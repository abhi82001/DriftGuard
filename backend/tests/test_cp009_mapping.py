#!/usr/bin/env python3
"""CP009 evidence-to-control lineage regression."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

from evidence.backbone import analyze_artifacts, EvidenceAnalysis
from evidence.mapping import map_questionnaire, REQUEST, NOT_EVALUATED, REVIEW
from fixtures import user_access_review_fixture as fx


def _q(view, number):
    return next(q for q in view.questions if q.question_id.endswith(f"Q{number:02d}"))


def test_1_policy_cannot_prove_mfa_enforcement():
    result = analyze_artifacts([("mfa_policy.txt",
        b"Multi-factor authentication is required for production systems.")])
    view = map_questionnaire(result)
    q = _q(view, 1)
    assert q.state == REQUEST
    assert q.expected_evidence == ("EV-IAM-001",)
    assert q.related_controls == ("SOC2-CC6.1-001",)
    assert "enforcement export" in q.explanation
    assert q.links and q.links[0].provenance
    assert _q(view, 2).state == NOT_EVALUATED


def test_2_real_access_review_links_question_and_provenance():
    analysis = analyze_artifacts([(fx.REAL_FILENAME, fx.real_workbook())])
    view = map_questionnaire(analysis)
    q = _q(view, 5)
    assert q.state == REVIEW
    assert q.expected_evidence == ("EV-ACCESS-001",)
    assert q.related_controls == ("SOC2-CC6.3-001",)
    assert q.links[0].artifact_id == analysis.artifacts[0].artifact_id
    assert any(p.container == "Access Review" for p in q.links[0].provenance)
    assert _q(view, 1).state == REQUEST


def test_3_no_artifact_means_evidence_request_not_control_failure():
    view = map_questionnaire(EvidenceAnalysis(()))
    assert _q(view, 1).state == REQUEST
    assert _q(view, 5).state == REQUEST
    payload = str(view.to_dict()).lower()
    assert "compliance_verdict" not in payload
    assert "control_pass" not in payload


def test_4_mapping_is_deterministic_and_nonmutating():
    analysis = analyze_artifacts([(fx.REAL_FILENAME, fx.real_workbook())])
    before = analysis.to_dict()
    assert map_questionnaire(analysis).to_dict() == map_questionnaire(analysis).to_dict()
    assert analysis.to_dict() == before


def test_5_bad_questionnaire_and_missing_record_rejected():
    import tempfile
    tmp_path = Path(tempfile.mkdtemp(prefix="cp009_kb_"))
    import json
    import shutil
    import pytest
    base = Path(__file__).resolve().parents[2] / "knowledge" / "soc2"
    (tmp_path / "questionnaires").mkdir()
    (tmp_path / "evidence").mkdir()
    (tmp_path / "controls").mkdir()
    record = json.loads((base / "questionnaires" / "QN-ACCESS-001.json").read_text())
    record["questions"][0]["expected_evidence"] = ["EV-NONEXISTENT"]
    (tmp_path / "questionnaires" / "QN-ACCESS-001.json").write_text(json.dumps(record))
    try:
        map_questionnaire(EvidenceAnalysis(()), knowledge_root=tmp_path)
    except ValueError as exc:
        assert "missing evidence" in str(exc)
    else:
        raise AssertionError("Missing evidence reference was accepted")


def test_6_http_endpoint_real_xlsx_and_policy():
    import asyncio
    import httpx
    from app import app

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            response = await client.post("/api/evidence-map", files=[
                ("files", ("Q3_Access_Review.xlsx", fx.real_workbook(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                ("files", ("mfa_policy.txt", b"Multi-factor authentication is required.", "text/plain")),
            ])
            assert response.status_code == 200
            payload = response.json()
            questions = {q["question_id"]: q for q in payload["mapping"]["questions"]}
            assert questions["QN-ACCESS-001-Q01"]["state"] == REQUEST
            review = questions["QN-ACCESS-001-Q05"]
            assert review["state"] == REVIEW
            assert review["links"][0]["provenance"]
            assert "compliance conclusion" in payload["disclaimer"]
    asyncio.run(check())


def run():
    failed = 0
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print("  PASS", name)
            except Exception as exc:
                failed += 1
                print("  FAIL", name, repr(exc))
    return failed


if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)
