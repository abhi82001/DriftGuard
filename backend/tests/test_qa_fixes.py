import json, os
from fastapi.testclient import TestClient
os.environ.setdefault("DRIFTGUARD_DEMO_MODE", "1")
import app as appmod

client = TestClient(appmod.app, follow_redirects=False)


def _export(files):
    r = client.post("/analyze", data={"vendor": "V"}, files=files)
    assert r.status_code == 303
    aid = r.headers["location"].rsplit("/", 1)[-1]
    return client.get(f"/export/{aid}").json()


def test_mfa_polarity_conflict_detected():
    out = _export([("files", ("a.txt", b"MFA is enforced for all users.", "text/plain")),
                   ("files", ("b.txt", b"MFA is optional for staff.", "text/plain"))])
    assert len(out["semantic_conflicts"]) >= 1
    assert out["semantic_conflicts"][0]["topic"] == "mfa"


def test_no_conflict_for_consistent_docs():
    out = _export([("files", ("a.txt", b"MFA is enforced for all users.", "text/plain")),
                   ("files", ("b.txt", b"MFA is required for staff.", "text/plain"))])
    assert out["semantic_conflicts"] == []


def test_zero_files_is_400_and_creates_nothing():
    n = len(appmod.DOC_ASSESSMENTS)
    r = client.post("/analyze", data={"vendor": "V"})
    assert r.status_code == 400 and "error" in r.json()
    assert len(appmod.DOC_ASSESSMENTS) == n


def test_unknown_ids_are_404():
    assert client.get("/doc-results/nope").status_code == 404
    assert client.get("/results/nope").status_code == 404


from pathlib import Path
PACK = Path(__file__).resolve().parents[2] / "test_evidence" / "driftguard_soc2_test_pack"
import pytest


def _analyze(names):
    from app import analyze_payloads
    return {a.question_id: a for a in analyze_payloads("t", [(Path(n).name, (PACK / n).read_bytes()) for n in names]).areas}


@pytest.mark.skipif(not PACK.exists(), reason="test pack missing")
def test_good_tabular_evidence_is_partially_established_not_established():
    a = _analyze(["07_Endpoint_Security/EDR_Coverage_Report.csv", "04_System_Operations/Log_Source_Coverage.csv"])
    assert a["QN-NETSEC-001-Q06"].status == "PARTIALLY_ESTABLISHED"
    assert a["QN-OPS-001-Q02"].status == "PARTIALLY_ESTABLISHED"
    assert a["QN-NETSEC-001-Q06"].known_facts[0].source_file == "EDR_Coverage_Report.csv"


@pytest.mark.skipif(not PACK.exists(), reason="test pack missing")
def test_weak_evidence_does_not_support_questions():
    a = _analyze(["01_Governance/Code_of_Conduct.docx"])
    assert all(x.status == "NOT_ESTABLISHED" for x in a.values())


@pytest.mark.skipif(not PACK.exists(), reason="test pack missing")
def test_every_emitted_finding_and_remediation_id_is_in_knowledge():
    import re
    from app import analyze_payloads
    files = [(f.name, f.read_bytes()) for f in sorted(PACK.rglob("*")) if f.is_file()
             and f.suffix.lower() in {".csv", ".xlsx", ".json", ".txt", ".docx", ".pdf"}]
    r = analyze_payloads("t", files)
    blob = json.dumps([c.to_dict() for e in r.evidence for c in e.checks], default=str) + json.dumps(
        [(x.question_id, x.reason, x.missing_facts, x.evidence_needed) for x in r.areas], default=str)
    emitted = set(re.findall(r"\b(?:FND|REM)-[A-Z]+-\d+\b|\bREM-[A-Z]+\b", blob))
    kb = Path(__file__).resolve().parents[2] / "knowledge" / "soc2"
    known = {p.stem for d in ("findings", "remediations") for p in (kb / d).glob("*.json")}
    assert emitted <= known, emitted - known
    assert not re.search(r"\bREM-(CLOSURE|CONFIRMATION)\b", blob)


def test_mixed_scope_sentence_is_not_a_conflict():
    out = _export([("files", ("a.txt", b"MFA is required for admins but optional for kiosks.", "text/plain")),
                   ("files", ("b.txt", b"MFA is enforced for all users.", "text/plain"))])
    assert out["semantic_conflicts"] == []


def test_conflict_shown_on_results_page():
    r = client.post("/analyze", data={"vendor": "V"}, files=[("files", ("a.txt", b"MFA is enforced for all users.", "text/plain")),
                                                             ("files", ("b.txt", b"MFA is optional for staff.", "text/plain"))])
    assert "Cross-document contradictions" in client.get(r.headers["location"]).text


@pytest.mark.skipif(not PACK.exists(), reason="test pack missing")
def test_needs_review_tabular_evidence_asks_clarification():
    a = _analyze(["02_IAM/Privileged_Account_Inventory.csv"])
    assert a["QN-ACCESS-001-Q08"].status == "CLARIFICATION_REQUIRED"
