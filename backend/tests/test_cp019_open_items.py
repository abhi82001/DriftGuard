"""CP019 open items: semantic omission, bridge-letter coverage, content-based authority."""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import assessment  # noqa: E402
from documents import apply_bridge_letters, resolve_authority  # noqa: E402
from evaluation.semantic import SemanticEvaluationResult, SemanticVerdict  # noqa: E402
from evidence.authority import ATTESTATION, PERIOD_COVERS, PERIOD_STALE, PRIVACY_GUIDANCE  # noqa: E402


def test_cp019_semantic_omitted_finding_is_not_evaluated(monkeypatch):
    monkeypatch.setattr(assessment, "_semantic_condition_id", lambda q: "COND-1")
    result = SemanticEvaluationResult(
        result_id="R1", condition_id="COND-1", question_id="Q1",
        assessment=SemanticVerdict.INSUFFICIENT.value, confidence=0.9,
        present_elements=(), missing_elements=("E1",), reason_codes=("element_not_mentioned",),
        needs_human_review=False, indicates_finding=None, notes=())
    runner = SimpleNamespace(run=lambda *a: result)
    q = {"question_id": "Q1", "text": "t", "answer_type": "free_text"}
    out = assessment._evaluate_one(SimpleNamespace(engine=None, finding_view=lambda f: None), runner, "", "src", "QN", q, "some answer")
    assert out.status == assessment.STATUS_NOT_EVALUATED
    assert out.status != assessment.STATUS_NO_GAP
    assert out.needs_review


def _doc(name, text):
    return SimpleNamespace(filename=name, text=text)


def test_cp019_bridge_letter_extends_period_only_when_scope_and_dates_match():
    soc_text = "Independent Service Auditor's Report SOC 2 Type 2. Period: 2024-01-01 to 2024-12-31"
    docs = [_doc("Azure SOC 2 Type 2.pdf", soc_text),
            _doc("Azure bridge letter.pdf", "Bridge letter. Report period ended 2024-12-31. Controls unchanged through 2025-09-30."),
            _doc("M365 bridge letter.pdf", "Bridge letter. Report period ended 2024-12-31. Controls unchanged through 2025-09-30.")]
    auths = apply_bridge_letters({d.filename: resolve_authority(d.filename, d.text) for d in docs}, docs)
    soc = auths["Azure SOC 2 Type 2.pdf"]
    as_of = date(2026, 2, 15)
    assert soc.authority == ATTESTATION and soc.period_end == "2024-12-31"
    assert soc.bridge_through == "2025-09-30" and soc.bridge_file == "Azure bridge letter.pdf"
    assert soc.period_state(as_of) == PERIOD_COVERS
    assert "M365 bridge letter.pdf not applied: scope" in soc.period_check   # wrong scope recorded
    # without a matching bridge the report is stale
    alone = apply_bridge_letters({"Azure SOC 2 Type 2.pdf": soc.__class__(**{**soc.__dict__, "bridge_through": ""})}, docs[:1])
    assert alone["Azure SOC 2 Type 2.pdf"].period_state(as_of) == PERIOD_STALE


def test_cp019_content_signal_overrides_misleading_filename_and_flags_it():
    soc = resolve_authority("vendor_notes.pdf",
                            "SOC 2 Type 2 Report\nIndependent Service Auditor's Report\nPeriod: 2024-01-01 to 2024-12-31")
    assert soc.authority == ATTESTATION and soc.report_type == "SOC2_TYPE2"
    assert soc.period_end == "2024-12-31"
    assert "content" in soc.review_flag
    pia = resolve_authority("SOC 2 Type 2 report.pdf", "Privacy Impact Assessment\nPurpose of this assessment")
    assert pia.authority == PRIVACY_GUIDANCE and pia.review_flag
    ok = resolve_authority("Azure SOC 2 Type 2.pdf", "SOC 2 Type 2 Independent Service Auditor's Report")
    assert ok.review_flag == ""
