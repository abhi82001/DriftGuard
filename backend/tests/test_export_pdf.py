"""GET /export-pdf/{assessment_id}: PDF export of a document assessment."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import app as webapp  # noqa: E402


def _assessment():
    a = webapp.ANALYZER.analyze("Acme Cloud Inc.", (), (), demo=True, evidence=())
    webapp.DOC_ASSESSMENTS[a.assessment_id] = a
    return a


def test_1_pdf_export_returns_pdf():
    a = _assessment()
    r = webapp.export_pdf(a.assessment_id)
    assert r.media_type == "application/pdf"
    assert r.body.startswith(b"%PDF")
    assert f"driftguard-{a.assessment_id}.pdf" in r.headers["content-disposition"]


def test_2_unknown_assessment_is_404():
    assert webapp.export_pdf("nope").status_code == 404


def test_3_results_page_has_download_pill():
    a = _assessment()
    page = webapp.doc_results(a.assessment_id).body.decode()
    assert f"/export-pdf/{a.assessment_id}" in page and "Download PDF" in page


TESTS = [test_1_pdf_export_returns_pdf, test_2_unknown_assessment_is_404, test_3_results_page_has_download_pill]

if __name__ == "__main__":
    bad = 0
    for t in TESTS:
        try:
            t(); print("  ok   ", t.__name__)
        except Exception as e:  # noqa: BLE001
            bad += 1; print("  FAIL ", t.__name__, type(e).__name__, e)
    sys.exit(1 if bad else 0)
