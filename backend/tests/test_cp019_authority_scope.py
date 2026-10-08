#!/usr/bin/env python3
"""CP019 step 1: evidence authority, scope, audit period, generic values, conflicts.

Small synthetic fixtures only; no vendor PDFs are committed.
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

import app as webapp  # noqa: E402
from claims import SecurityClaim  # noqa: E402
from documents import CONFLICT, ESTABLISHED, NOT_ESTABLISHED, PARTIAL  # noqa: E402
from evidence.authority import (ATTESTATION, CONTRACT, MARKETING, PERIOD_COVERS, PERIOD_STALE,  # noqa: E402
                                PERIOD_UNKNOWN, PRIVACY_GUIDANCE, SUBPROCESSOR_LIST, UNCLASSIFIED,
                                can_establish, classify_document)
from evidence.specificity import is_specific  # noqa: E402

AS_OF = date(2026, 10, 8)
MFA_TEXT = ("Multi-factor authentication is required for administrators accessing production systems. "
            "Multi-factor authentication is enforced and enabled for production systems.")
ANALYZER = webapp.ANALYZER


def _claims(filename, text="mfa", attrs=None, nature="CONFIGURATION"):
    attrs = attrs or {"requirement": "required", "scope": ["production systems"], "enforcement_evidence": True}
    return [SecurityClaim("mfa", MFA_TEXT, filename, f"page {i}", MFA_TEXT,
                          nature if k == "enforcement_evidence" else "POLICY", {k: v})
            for i, (k, v) in enumerate(attrs.items(), start=1)]


def _q01(claims, filenames, as_of=AS_OF):
    from ingestion import Chunk, Document
    docs = [Document(f, "artifact", (Chunk(f, "page 1", MFA_TEXT),)) for f in filenames]

    class Fixed:
        def extract(self, _):
            return claims
    from documents import DocumentAnalyzer
    a = DocumentAnalyzer(ANALYZER.knowledge, extractor=Fixed())
    res = a.analyze("v", docs, [], True, assessment_date=as_of)
    return next(x for x in res.areas if x.question_id == "QN-ACCESS-001-Q01")


def test_authority_classes():
    assert classify_document("Azure - SOC 2 Type II Report (04-01-2025 to 3-31-2026).pdf").authority == ATTESTATION
    assert classify_document("Azure SOC Bridge Letter (July 1, 2026 - September 30, 2026).pdf").report_type == "BRIDGE_LETTER"
    assert classify_document("Azure Foundational Privacy Impact Assessment (December 2025).pdf").authority == PRIVACY_GUIDANCE
    assert classify_document("Build Your Own O365 DPIA (5.15.2025).docx").authority == PRIVACY_GUIDANCE
    assert classify_document("Data protection terms for products (March 2023).pdf").authority == CONTRACT
    assert classify_document("Accelerating Trust and Innovation in Latin America.pdf").authority == MARKETING
    assert classify_document("Online Services Subprocessors List (2026-09-10).pdf").authority == SUBPROCESSOR_LIST
    assert classify_document("Access_Control_Policy.txt").authority == UNCLASSIFIED


def test_scope_report_type_and_period_are_tagged():
    a = classify_document("Azure + Dynamics 365 - Public & Government SOC 1 Type II Report (July 1, 2025 - June 30, 2026).pdf")
    assert (a.scope, a.report_type, a.period_start, a.period_end) == ("AZURE", "SOC1_TYPE2", "2025-07-01", "2026-06-30")
    assert classify_document("Azure DevOps - SOC 2 Type II Report (2024-10-01-to 2025-09-30).pdf").scope == "AZURE_DEVOPS"
    assert classify_document("Microsoft 365 Central Services - SOC 2 Type 2 Report (9-30-2025).pdf").scope == "M365_CENTRAL_SERVICES"
    d = classify_document("Azure Databricks - Databricks, Inc. - 2025 SOC 1 Type 2 Report (11-1-2024 to 10-31-2025).pdf")
    assert d.third_party and d.period_start == "2024-11-01"
    assert classify_document("Nuance Healthcare Cloud - SOC 2 (2026).pdf").period_state(AS_OF) == PERIOD_UNKNOWN


def test_period_validity_uses_assessment_date():
    soc = classify_document("Azure SOC 2 Type II Report (04-01-2025 to 3-31-2026).pdf")
    assert soc.period_state(date(2025, 12, 1)) == PERIOD_COVERS
    assert soc.period_state(date(2027, 6, 1)) == PERIOD_STALE


def test_non_attestations_and_third_party_cannot_establish():
    for name in ("Azure Privacy Impact Assessment.pdf", "Data protection terms.pdf", "Trust and Innovation brochure.pdf"):
        assert not can_establish(classify_document(name))[0]
    assert not can_establish(classify_document("Nuance Dragon Medical SOC 2 (2026).pdf"))[0]
    assert can_establish(classify_document("Azure SOC 2 Type II Report (04-01-2025 to 3-31-2026).pdf"))[0]


def test_brochure_and_third_party_report_do_not_establish_control():
    names = ["Trust and Innovation in Latin America brochure.pdf", "Nuance Dragon Medical SOC 2 (2026).pdf"]
    area = _q01(sum((_claims(n) for n in names), []), names)
    assert area.status == NOT_ESTABLISHED and not area.known_facts
    assert {c["filename"] for c in area.context_sources + area.rejected_sources} == set(names)


def test_stale_period_is_rejected_not_established():
    name = "Azure SOC 2 Type II Report (04-01-2023 to 3-31-2024).pdf"
    area = _q01(_claims(name), [name])
    assert area.status == NOT_ESTABLISHED
    assert "12 months" in area.rejected_sources[0]["reason"]


def test_in_period_single_scope_attestation_can_establish_with_scope_tags():
    name = "Azure SOC 2 Type II Report (04-01-2025 to 3-31-2026).pdf"
    area = _q01(_claims(name), [name])
    assert area.status == ESTABLISHED
    assert {f.scope for f in area.known_facts} == {"AZURE"} and area.known_facts[0].audit_period == "2025-04-01 to 2026-03-31"


def test_unknown_period_attestation_is_capped_at_partial():
    name = "Azure SOC 2 Type II Report.pdf"
    area = _q01(_claims(name), [name])
    assert area.status == PARTIAL and any("audit period" in m for m in area.missing_facts)


def test_different_scopes_are_separate_observations_not_a_conflict():
    a = "Azure SOC 2 Type II Report (04-01-2025 to 3-31-2026).pdf"
    b = "Microsoft 365 Central Services SOC 2 Type 2 Report (3-31-2026).pdf"
    ca = [SecurityClaim("privileged_access", "JIT elevated access is time-bound for production", a, "p1", "JIT elevated access is time-bound for production",
                        "POLICY", {"privilege_model": "time-bounded"})]
    cb = [SecurityClaim("privileged_access", "Standing administrative access is used in this service", b, "p2", "Standing administrative access is used in this service",
                        "POLICY", {"privilege_model": "standing"})]
    from documents import DocumentAnalyzer
    from ingestion import Chunk, Document
    docs = [Document(f, "artifact", (Chunk(f, "page 1", "x"),)) for f in (a, b)]

    class Fixed:
        def extract(self, _):
            return ca + cb
    res = DocumentAnalyzer(ANALYZER.knowledge, extractor=Fixed()).analyze("v", docs, [], True, assessment_date=AS_OF)
    q08 = next(x for x in res.areas if x.question_id == "QN-ACCESS-001-Q08")
    assert q08.status != CONFLICT
    assert {o["scope"] for o in q08.scoped_observations} == {"AZURE", "M365_CENTRAL_SERVICES"}


def test_same_scope_contradiction_names_both_facts_sources_and_difference():
    a = "Azure SOC 2 Type II Report (04-01-2025 to 3-31-2026).pdf"
    mk = lambda loc, val: SecurityClaim("privileged_access", "Privileged access model statement for production",
                                        a, loc, "Privileged access model statement for production", "POLICY", {"privilege_model": val})
    from documents import DocumentAnalyzer
    from ingestion import Chunk, Document

    class Fixed:
        def extract(self, _):
            return [mk("page 3", "standing"), mk("page 9", "time-bounded")]
    res = DocumentAnalyzer(ANALYZER.knowledge, extractor=Fixed()).analyze(
        "v", [Document(a, "artifact", (Chunk(a, "page 1", "x"),))], [], True, assessment_date=AS_OF)
    q08 = next(x for x in res.areas if x.question_id == "QN-ACCESS-001-Q08")
    d = q08.conflict_details[0]
    assert q08.status == CONFLICT
    assert {d["value_a"], d["value_b"]} == {"standing", "time-bounded"}
    assert d["scope"] == "AZURE" and d["file_a"] == d["file_b"] == a and {d["locator_a"], d["locator_b"]} == {"page 3", "page 9"}
    assert "page 3" in q08.reason and "page 9" in q08.reason


def test_generic_value_needs_question_specific_context():
    mk = lambda snippet: SecurityClaim("alert_triage", snippet, "f.pdf", "p1", snippet, "REPORT", {"triage_requirement": "required"})
    assert not is_specific(mk("This is required."), "triage_requirement", "alert_triage")
    assert not is_specific(mk("Brochure copy about innovation in the region is required reading"), "triage_requirement", "alert_triage")
    assert is_specific(mk("Security alerts must be triaged by the on-call analyst within one hour"), "triage_requirement", "alert_triage")
    assert is_specific(SecurityClaim("privileged_access", "x", "f", "p", "x", "REPORT", {"privilege_model": "standing"}), "privilege_model", "privileged_access")
