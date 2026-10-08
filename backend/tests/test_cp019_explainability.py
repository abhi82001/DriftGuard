#!/usr/bin/env python3
"""CP019 step 3: question-level explanations, grouped gap requests, customer labels."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from documents import AreaResult, Fact  # noqa: E402
from evidence.report import CUSTOMER_STATUS_LABELS, build_question_reports, status_label  # noqa: E402

VERDICT = re.compile(r"\b(compliant|non-compliant|pass(?:ed)?|fail(?:ed|ure)?|certified|audit opinion)\b", re.I)
INTERNAL = ("ESTABLISHED", "PARTIALLY_ESTABLISHED", "NOT_ESTABLISHED", "CLARIFICATION_REQUIRED", "CONFLICT", "NOT_EVALUATED")


def area(qid, status, missing=(), needed=("Access Review Record",), facts=(), **kw):
    return AreaResult("QN-X", qid, "Access", f"Question {qid}?", status, f"reason for {qid}",
                      known_facts=list(facts), missing_facts=list(missing), evidence_needed=list(needed), **kw)


FACT = Fact("cadence", "cadence: quarterly", "policy.txt", "line 3", "Access reviews run quarterly.", "POLICY",
            scope="AZURE", report_type="SOC2_TYPE2", audit_period="2025-04-01 to 2026-03-31")


def test_labels_map_one_to_one_and_use_no_verdict_words():
    assert set(CUSTOMER_STATUS_LABELS) == set(INTERNAL)
    assert len(set(CUSTOMER_STATUS_LABELS.values())) == len(INTERNAL)
    assert not any(VERDICT.search(v) for v in CUSTOMER_STATUS_LABELS.values())
    assert status_label("CONFLICT") == "Sources disagree"


def test_every_question_explains_status_why_facts_files_and_missing():
    rpt = build_question_reports([
        area("Q1", "ESTABLISHED", facts=[FACT]),
        area("Q2", "PARTIALLY_ESTABLISHED", missing=["the most recent completed review"], facts=[FACT],
             rejected_sources=[dict(filename="old.pdf", authority="ATTESTATION", scope="AZURE_DEVOPS", reason="audit period ends more than 12 months before the assessment date")],
             context_sources=[dict(filename="brochure.pdf", authority="MARKETING", reason="marketing informs context but cannot establish a control")]),
    ])
    q1, q2 = rpt["questions"]
    assert q1["status_label"] == "Supported by supplied evidence" and q1["files_used"] == ["policy.txt"]
    assert q1["facts_used"][0]["scope"] == "AZURE" and q1["facts_used"][0]["locator"] == "line 3"
    assert q1["missing"] == ["Nothing further requested for this question."]
    assert q2["why"] == "reason for Q2" and q2["gap_kind"] == "PROVIDED_BUT_INSUFFICIENT"
    assert q2["rejected_sources"][0]["why"].startswith("audit period") and q2["context_only_sources"][0]["filename"] == "brochure.pdf"
    assert q2["missing"] == ["the most recent completed review"] and "Provide a document" in q2["remediation"][0]


def test_missing_item_is_never_a_dash_and_every_gap_has_remediation():
    rpt = build_question_reports([area("Q3", "NOT_ESTABLISHED", missing=["—", " "]),
                                  area("Q4", "CLARIFICATION_REQUIRED", missing=[], needed=())])
    for q in rpt["questions"]:
        assert q["missing"] and all(m.strip() not in ("", "—") for m in q["missing"])
        assert len(q["remediation"]) == len(q["missing"]) and all(r.strip() for r in q["remediation"])


def test_gaps_group_by_document_type_listing_affected_questions():
    rpt = build_question_reports([
        area("Q1", "NOT_ESTABLISHED", needed=("Access Review Record", "IdP Export")),
        area("Q2", "NOT_ESTABLISHED", needed=("Access Review Record",)),
        area("Q3", "PARTIALLY_ESTABLISHED", missing=["population"], needed=("Access Review Record",)),
    ])
    missing = {g["document_type"]: g for g in rpt["evidence_missing"]}
    assert missing["Access Review Record"]["questions"] == ["Q1", "Q2"]
    assert missing["IdP Export"]["questions"] == ["Q1"]
    insufficient = rpt["provided_but_insufficient_or_conflicting"]
    assert [g["questions"] for g in insufficient] == [["Q3"]]
    assert all(g["remediation"] for g in rpt["evidence_missing"] + insufficient)


def test_conflict_is_separated_and_unread_material_is_not_missing_evidence():
    rpt = build_question_reports(
        [area("Q5", "CONFLICT", missing=["resolve conflict: privilege model"])],
        extraction=[dict(filename="scan.pdf", status="UNREADABLE_SCAN_NEEDS_OCR", remediation="enable OCR"),
                    dict(filename="b.pdf", status="DUPLICATE", duplicate_of="a.pdf"),
                    dict(filename="a.pdf", status="EXTRACTED")])
    assert rpt["questions"][0]["gap_kind"] == "PROVIDED_BUT_CONFLICTING"
    assert rpt["evidence_missing"] == [] and rpt["provided_but_insufficient_or_conflicting"][0]["kind"] == "PROVIDED_BUT_CONFLICTING"
    assert [u["filename"] for u in rpt["unread_material"]] == ["scan.pdf"] and [d["filename"] for d in rpt["duplicates"]] == ["b.pdf"]
    assert "Confirm which source applies" in rpt["questions"][0]["remediation"][0]


def test_output_contains_no_verdict_words():
    rpt = build_question_reports([area("Q1", "ESTABLISHED", facts=[FACT]), area("Q2", "NOT_ESTABLISHED"), area("Q3", "CONFLICT")])
    blob = str([{k: q[k] for k in ("status_label", "missing", "remediation")} for q in rpt["questions"]])
    assert not VERDICT.search(blob)
