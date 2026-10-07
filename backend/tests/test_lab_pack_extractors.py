"""Operational-register extractors and the 11-file synthetic lab pack (no AI/semantic calls)."""
import datetime
from pathlib import Path

import pytest

import app as app_module
import ingestion
import upload_security
from evidence.operational_registers import map_headers, reconcile
from evidence.pipeline import analyze_evidence_file

PACK = Path(__file__).parent / "fixtures" / "lab_pack"
AS_OF = datetime.date(2025, 12, 31)
FILES = sorted(p.name for p in PACK.iterdir())


def _bytes(name):
    return (PACK / name).read_bytes()


def _payloads(*names):
    return [(n, _bytes(n)) for n in names]


def _counts(name):
    r = analyze_evidence_file(name, _bytes(name), as_of=AS_OF)
    return r, {c.check_id: len(c.inputs.get("records", ())) for c in r.checks}


def test_pack_has_eleven_files():
    assert len(FILES) == 11


@pytest.mark.parametrize("name,kind,rows", [
    ("access_review_Q2_2025.csv", "ACCESS_REVIEW_LOG", 48),
    ("approved_privileged_users.csv", "PRIVILEGED_APPROVAL_LIST", 4),
    ("backup_jobs.csv", "BACKUP_JOB_REPORT", 356),
    ("incident_register.csv", "INCIDENT_REGISTER", 12),
    ("jira_change_population.csv", "CHANGE_POPULATION", 60),
    ("vendor_register.csv", "VENDOR_REGISTER", 10),
    ("training_records.csv", "TRAINING_RECORDS", 60),
    ("vuln_scan_export.csv", "VULNERABILITY_REMEDIATION", 80),
])
def test_previously_unclassified_files_are_recognized(name, kind, rows):
    r, _ = _counts(name)
    assert r.evidence_type == kind and r.extractor == "operational-register-v1"
    assert next(f.value for f in r.facts if f.key == "record_count") == rows


def test_okta_and_hris_are_recognized_and_okta_keys_read():
    okta, _ = _counts("okta_users.csv")
    assert okta.evidence_type == "IDENTITY_PROVIDER_EXPORT" and okta.state == "SUPPORTED"
    assert analyze_evidence_file("hris_terminations.csv", _bytes("hris_terminations.csv")).evidence_type \
        == "HR_ACTIVE_WORKER_ROSTER"


def test_backup_failures_and_missing_days():
    _, c = _counts("backup_jobs.csv")
    assert c == {"BACKUP-RUN-FAILED": 6, "BACKUP-RUN-MISSING": 9}


def test_change_findings():
    _, c = _counts("jira_change_population.csv")
    assert c == {"CHANGE-NO-APPROVAL": 5, "CHANGE-APPROVAL-AFTER-DEPLOY": 3,
                 "CHANGE-SELF-REVIEWED": 3, "CHANGE-DEPLOYED-FAILED-CI": 3}


def test_vulnerability_sla_breaches():
    _, c = _counts("vuln_scan_export.csv")
    assert c == {"VULN-SLA-BREACH": 30}


def test_training_incident_vendor_findings():
    assert _counts("training_records.csv")[1] == {"TRAINING-NOT-COMPLETED": 6}
    assert _counts("incident_register.csv")[1] == {"INCIDENT-NO-POSTMORTEM": 2}
    assert _counts("vendor_register.csv")[1] == {"VENDOR-REVIEW-OVERDUE": 3}


def test_clean_review_and_approval_files_are_supported():
    for n in ("access_review_Q2_2025.csv", "approved_privileged_users.csv"):
        assert analyze_evidence_file(n, _bytes(n), as_of=AS_OF).state == "SUPPORTED"


def test_cross_file_findings():
    found = {f.code: [i for _, i in f.records] for _, f in reconcile(
        _payloads(*[n for n in FILES if n.endswith(".csv")]), as_of=AS_OF)}
    assert found["TERMINATED-USER-ACTIVE"] == ["u001", "u007", "u008"]
    assert found["UNAPPROVED-PRIVILEGED-USER"] == ["u017", "u033"]   # u017: deprovisioned yet still in Admins
    assert found["MFA-NOT-ENROLLED"] == ["u006", "u034", "u043", "u057"]
    assert found["DORMANT-ACCOUNT-90D"] == ["u002", "u005", "u027", "u037"]
    assert len(found["USER-MISSING-FROM-REVIEW"]) == 12
    assert "ORPHAN-PRIVILEGE-APPROVAL" not in found


def test_orphan_privilege_approval_detected():
    idp = b"id,login,status,lastLogin,mfaEnrolled,group\nu1,a@x.test,ACTIVE,2025-12-01,true,Admins\n"
    approved = (b"employee_id,email,approved_by,approved_date\n"
                b"u1,a@x.test,ciso@x.test,2025-01-01\nu9,gone@x.test,ciso@x.test,2025-01-01\n")
    found = {f.code: [i for _, i in f.records] for _, f in
             reconcile([("idp.csv", idp), ("approved.csv", approved)], as_of=AS_OF)}
    assert found == {"ORPHAN-PRIVILEGE-APPROVAL": ["u9"]}


def test_headers_matched_by_synonym_not_exact_name():
    m = map_headers(["Employee ID", "E-Mail", "Review Decision", "Reviewed By", "Reviewed On"])
    assert m["id"] == "Employee ID" and m["decision"] == "Review Decision" and m["review_date"] == "Reviewed On"
    csv = (b"Worker Id,Email Address,Decision,Reviewer,Review Date\n"
           b"w1,a@x.test,Retain,m@x.test,2025-04-01\n")
    assert analyze_evidence_file("renamed.csv", csv).evidence_type == "ACCESS_REVIEW_LOG"


def test_unclassified_file_is_never_a_failure():
    junk = b"foo,bar\n1,2\n3,4\n"
    r = analyze_evidence_file("junk.csv", junk)
    assert r.evidence_type == "UNCLASSIFIED" and r.state == "MISSING"
    base = _payloads("stated_policy_requirements.md")
    a = app_module.analyze_payloads("t", base).counts
    b = app_module.analyze_payloads("t", base + [("junk.csv", junk)]).counts
    assert {k: v for k, v in a.items() if k != "documents_analyzed"} == \
           {k: v for k, v in b.items() if k != "documents_analyzed"}


def test_recognized_clean_file_reaches_established():
    res = app_module.analyze_payloads("t", _payloads("stated_policy_requirements.md", "access_review_Q2_2025.csv"),
                                      assessment_date=AS_OF)
    q03 = next(a for a in res.areas if a.question_id == "QN-ACCESS-001-Q03")
    assert q03.status == "ESTABLISHED"


def test_full_pack_status_counts():
    res = app_module.analyze_payloads("lab", _payloads(*FILES), assessment_date=AS_OF)
    assert res.counts == {"documents_analyzed": 11, "established": 1, "partially_established": 1,
                          "missing_evidence": 20, "clarification_required": 6, "conflict": 1,
                          "not_evaluated": 0}
    by = {a.question_id: a.status for a in res.areas}
    # True conflict: HRIS says terminated, IdP says active, policy requires deprovisioning within 1 day.
    assert by["QN-ACCESS-001-Q06"] == "CONFLICT"
    assert by["QN-ACCESS-001-Q08"] == "CLARIFICATION_REQUIRED"


def test_upload_limit_is_25_everywhere():
    assert ingestion.MAX_FILES == upload_security.MAX_UPLOAD_FILES == 25
    assert "max 25 files" in Path(app_module.__file__).read_text(encoding="utf-8")
