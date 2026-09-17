#!/usr/bin/env python3
"""CP007 Evidence QA report tests (presentation layer only).

These prove the report re-words and re-orders what validation already decided,
without inventing facts, advice, or losing a single cell reference.
"""

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

from test_mvp_app import _call  # noqa: E402  (shared ASGI caller, no network)

import app as webapp  # noqa: E402
from evaluation.semantic import PROHIBITED_VERDICTS  # noqa: E402
from evidence import (  # noqa: E402
    CONFLICT,
    MISSING,
    NEEDS_REVIEW,
    NOT_A_FAILURE,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    analyze_evidence,
    analyze_evidence_file,
    build_report,
)
from evidence.validation import (  # noqa: E402
    CHECK_CONSISTENCY,
    CHECK_DECISIONS,
    CHECK_IDENTITY,
    CHECK_POPULATION,
    CHECK_POST_CHANGE,
    CHECK_REMEDIATION,
)
from fixtures import user_access_review_fixture as fx  # noqa: E402

# "CERTIFIED" is the customer's own column wording ("Reviewed / Certified
# Accounts"), quoted verbatim in the facts table. It is artifact vocabulary, not
# a verdict DriftGuard asserts, so it is excluded from the page-wide scan and
# still checked against everything DriftGuard itself writes.
_ARTIFACT_VOCABULARY = {"CERTIFIED"}

_CACHE: dict = {}


def _report(name: str):
    if name not in _CACHE:
        builder = {"clean": (fx.CLEAN_FILENAME, fx.clean_workbook),
                   "conflict": (fx.WORKBOOK_FILENAME, fx.campaign_workbook),
                   "csv": (fx.CSV_FILENAME, fx.summary_csv)}[name]
        _CACHE[name] = build_report(analyze_evidence_file(builder[0], builder[1]()))
    return _CACHE[name]


def _line(report, check_id):
    return next(x for x in report.exceptions + report.reconciled
                if x.check_id == check_id)


# ---------------------------------------------------------------------- 1
def test_1_fully_reconciled_artifact_has_no_exceptions():
    report = _report("clean")
    assert report.exception_count == 0
    assert report.exceptions == ()
    assert report.state == SUPPORTED
    assert report.review_period == "2026-01-01 to 2026-03-31"
    assert report.campaign_status == "Closed"

    reconciled = {x.check_id: x for x in report.reconciled}
    assert {CHECK_POPULATION, CHECK_DECISIONS, CHECK_REMEDIATION, CHECK_POST_CHANGE,
            CHECK_IDENTITY, CHECK_CONSISTENCY} <= set(reconciled)
    assert all(x.state == SUPPORTED for x in report.reconciled)

    assert (f"{fx.CLEAN_SOURCE_POPULATION} accounts extracted, "
            f"{fx.CLEAN_EXCLUDED} excluded, {fx.CLEAN_REVIEWED} reviewed"
            in reconciled[CHECK_POPULATION].headline)
    assert (f"All {fx.CLEAN_REVIEWED} reviewed accounts carry a reviewer decision"
            in reconciled[CHECK_DECISIONS].headline)
    assert "0 unresolved" in reconciled[CHECK_REMEDIATION].headline


# ---------------------------------------------------------------------- 2
def test_2_contradiction_is_the_first_exception_with_both_values():
    report = _report("conflict")
    assert report.exception_count > 0
    first = report.exceptions[0]
    assert first.state == CONFLICT
    assert first.check_id == CHECK_CONSISTENCY
    assert "excluded population disagrees" in first.headline
    assert f"{fx.SUMMARY_EXCLUDED} vs {fx.EXCLUSION_ROWS}" in first.headline

    locators = {(p.sheet, p.locator) for p in first.provenance}
    assert locators == {(fx.SUMMARY_SHEET, fx.EXCLUDED_CELL),
                        (fx.EXCLUSIONS_SHEET, fx.EXCLUSIONS_RANGE)}

    # The dependent reconciliation is reported next, and says why it stopped.
    states = [x.state for x in report.exceptions]
    assert states == sorted(states, key=lambda s: [CONFLICT, NEEDS_REVIEW,
                                                   PARTIALLY_SUPPORTED, MISSING].index(s))
    population = _line(report, CHECK_POPULATION)
    assert population.state == NEEDS_REVIEW
    assert population.headline.startswith("Population cannot be reconciled")
    assert f"{fx.SUMMARY_EXCLUDED} vs {fx.EXCLUSION_ROWS}" in population.headline


# ---------------------------------------------------------------------- 3
def test_3_open_remediation_headline_and_provenance():
    workbook = _line(_report("conflict"), CHECK_REMEDIATION)
    assert workbook.state == PARTIALLY_SUPPORTED
    assert workbook.headline == (
        f"{fx.SUMMARY_REVOKE + fx.SUMMARY_MODIFY} access changes flagged, "
        f"{fx.SUMMARY_REMEDIATION_COMPLETED} completed - "
        f"{fx.SUMMARY_REMEDIATION_OPEN} unresolved")
    assert "9 unresolved" in workbook.headline
    assert any(p.locator == f"{fx.DETAIL_RANGE} column F" for p in workbook.provenance)
    assert any(p.locator == "B19" for p in workbook.provenance)

    csv_line = _line(_report("csv"), CHECK_REMEDIATION)
    assert csv_line.headline.endswith(f"{fx.CSV_OPEN_REMEDIATION} unresolved")
    assert csv_line.provenance


# ---------------------------------------------------------------------- 4
def test_4_missing_checks_are_exceptions_without_failure_language():
    report = _report("csv")
    missing = [x for x in report.exceptions if x.state == MISSING]
    assert {x.check_id for x in missing} >= {CHECK_POST_CHANGE, CHECK_IDENTITY}
    assert all(x.state_word == "Not in this artifact" for x in missing)

    for line in missing:
        assert "in this artifact" in line.headline
        # A check without its own headline in report.py is shown through its
        # validator detail, which carries DriftGuard's "not a control failure"
        # disclaimer. That sentence is the denial of failure language, not an
        # instance of it, so it is removed before the scan rather than banned.
        blob = line.headline.lower().replace(NOT_A_FAILURE.lower(), "")
        for word in ("fail", "failure", "non-compliant", "violation", "deficien",
                     "should", "must", "recommend"):
            assert word not in blob, (line.check_id, word)

    # MISSING is ordered last, after anything partly evidenced.
    assert [x.state for x in report.exceptions][-len(missing):] == [MISSING] * len(missing)


# ---------------------------------------------------------------------- 5
def test_5_every_rendered_provenance_matches_the_result_object():
    payloads = [(fx.WORKBOOK_FILENAME, fx.campaign_workbook()),
                (fx.CSV_FILENAME, fx.summary_csv())]
    results = analyze_evidence(payloads)

    from ingestion import extract_many

    documents, errors = extract_many(payloads)
    a = webapp.ANALYZER.analyze("Acme Cloud Inc.", documents, errors, demo=True,
                                evidence=results)
    webapp.DOC_ASSESSMENTS[a.assessment_id] = a
    status, text, _ = _call("GET", f"/evidence-report/{a.assessment_id}")
    assert status == 200

    rendered = 0
    for result in results:
        for holder in list(result.facts) + list(result.checks):
            for p in holder.provenance:
                assert str(p) in text, str(p)
                assert p.locator in text
                rendered += 1
    assert rendered > 20

    # The report is reachable from the document results page.
    _, doc_text, _ = _call("GET", f"/doc-results/{a.assessment_id}")
    assert f"/evidence-report/{a.assessment_id}" in doc_text
    assert "Evidence QA" in doc_text

    # Headlines and section structure survive rendering.
    report = build_report(results[0])
    assert f"Needs attention ({report.exception_count})" in text
    assert report.exceptions[0].headline in text
    assert report.reconciled[0].headline in text
    assert report.exceptions[0].check_id in text      # trace label retained


# ---------------------------------------------------------------------- 6
def test_6_rendered_report_asserts_no_compliance_verdict():
    payloads = [(fx.WORKBOOK_FILENAME, fx.campaign_workbook()),
                (fx.CLEAN_FILENAME, fx.clean_workbook()),
                (fx.NON_REVIEW_FILENAME, fx.NON_REVIEW_CSV)]

    from ingestion import extract_many

    documents, errors = extract_many(payloads)
    a = webapp.ANALYZER.analyze("Acme Cloud Inc.", documents, errors, demo=True,
                                evidence=analyze_evidence(payloads))
    webapp.DOC_ASSESSMENTS[a.assessment_id] = a
    _, text, _ = _call("GET", f"/evidence-report/{a.assessment_id}")
    page = text.upper()

    for banned in PROHIBITED_VERDICTS - _ARTIFACT_VOCABULARY:
        assert banned not in page, banned
    assert "not a SOC 2 compliance conclusion" in text

    # Everything DriftGuard itself writes is clean, including the excluded term.
    for result in analyze_evidence(payloads):
        report = build_report(result)
        authored = " ".join(
            [report.state, *report.notes]
            + [f"{x.state_word} {x.headline} {x.name}"
               for x in report.exceptions + report.reconciled]
        ).upper()
        for banned in PROHIBITED_VERDICTS:
            assert banned not in authored, banned


TESTS = [
    test_1_fully_reconciled_artifact_has_no_exceptions,
    test_2_contradiction_is_the_first_exception_with_both_values,
    test_3_open_remediation_headline_and_provenance,
    test_4_missing_checks_are_exceptions_without_failure_language,
    test_5_every_rendered_provenance_matches_the_result_object,
    test_6_rendered_report_asserts_no_compliance_verdict,
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
