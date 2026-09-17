#!/usr/bin/env python3
"""CP007 Phase 1 tests: XLSX/CSV -> classify -> extract with provenance ->
deterministic reconciliation -> structured evidence result.

The fixtures are built in memory by fixtures/user_access_review_fixture.py.
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
    EVIDENCE_STATES,
    MISSING,
    NEEDS_REVIEW,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNCLASSIFIED,
    USER_ACCESS_REVIEW,
    EvidenceFact,
    Provenance,
    analyze_evidence,
    analyze_evidence_file,
    read_tabular,
)
from evidence.extractors import base as extractor_registry  # noqa: E402
from evidence.validation import (  # noqa: E402
    CHECK_CONSISTENCY,
    CHECK_DECISION_COVERAGE,
    CHECK_DECISIONS,
    CHECK_IDENTITY,
    CHECK_PERIOD,
    CHECK_POPULATION,
    CHECK_POST_CHANGE,
    CHECK_REMEDIATION,
    validate_user_access_review,
)
from fixtures import user_access_review_fixture as fx  # noqa: E402

_WORKBOOK = None


def _workbook_result():
    global _WORKBOOK
    if _WORKBOOK is None:
        _WORKBOOK = analyze_evidence_file(fx.WORKBOOK_FILENAME, fx.campaign_workbook())
    return _WORKBOOK


def _csv_result():
    return analyze_evidence_file(fx.CSV_FILENAME, fx.summary_csv())


# ---------------------------------------------------------------------- 1
def test_1_file_is_classified_as_user_access_review():
    result = _workbook_result()
    assert result.evidence_type == USER_ACCESS_REVIEW
    assert result.knowledge_evidence_id == "EV-ACCESS-001"   # existing knowledge ID
    assert result.classification_confidence == 1.0
    assert _csv_result().evidence_type == USER_ACCESS_REVIEW

    # A tabular upload that is not a review stays unclassified, and that is an
    # unread artifact - not a negative result about a control.
    other = analyze_evidence_file(fx.NON_REVIEW_FILENAME, fx.NON_REVIEW_CSV)
    assert other.evidence_type == UNCLASSIFIED
    assert other.state == MISSING
    assert not other.facts and not other.checks
    assert "not a negative result about any control" in " ".join(other.notes)

    # Structure is preserved on the way in: sheets, headers, addressable cells.
    workbook = read_tabular(fx.WORKBOOK_FILENAME, fx.campaign_workbook())
    assert [s.name for s in workbook.sheets] == [
        fx.SUMMARY_SHEET, fx.DETAIL_SHEET, fx.EXCLUSIONS_SHEET]
    detail = workbook.sheets[1]
    assert detail.header_row == 1
    assert "review decision" in detail.headers
    assert len(detail.data_rows) == fx.SUMMARY_REVIEWED
    summary = workbook.sheets[0]
    assert summary.header_row is None          # a label/value sheet has no header
    assert summary.rows[10].cell(2).ref == fx.EXCLUDED_CELL


# ---------------------------------------------------------------------- 2
def test_2_structured_facts_are_extracted():
    result = _workbook_result()
    expected = {
        "campaign_name": "Q3-2026-UAR-PROD",
        "campaign_status": "Closed",
        "review_period_start": "2026-07-01",
        "review_period_end": "2026-09-30",
        "review_completed_date": "2026-10-05",
        "source_population": fx.SUMMARY_SOURCE_POPULATION,
        "reviewed_population": fx.SUMMARY_REVIEWED,
        "decision_retain": fx.SUMMARY_RETAIN,
        "decision_modify": fx.SUMMARY_MODIFY,
        "decision_revoke": fx.SUMMARY_REVOKE,
        "decision_investigate": fx.SUMMARY_INVESTIGATE,
        "remediation_completed": fx.SUMMARY_REMEDIATION_COMPLETED,
        "remediation_open": fx.SUMMARY_REMEDIATION_OPEN,
        "exceptions_open": fx.SUMMARY_EXCEPTIONS,
    }
    for key, value in expected.items():
        assert result.value(key) == value, key

    # excluded population is present as a fact, but contradicted (see test 7).
    assert result.fact("excluded_population") is not None

    # Identity populations, including the ones whose omission is the classic
    # scope defect for this artifact.
    populations = dict(result.value("identity_populations"))
    assert populations == {"employee": 80, "contractor": 15,
                           "service_account": 10, "privileged": 7}
    assert sum(populations.values()) == fx.SUMMARY_REVIEWED

    # Corroboration is recorded: the summary and the detail sheet agree.
    assert result.fact("decision_revoke").derivation == "counted+stated"
    assert result.fact("identity_populations").derivation == "counted"

    # The CSV summary yields the same normalized keys from a different shape.
    csv_result = _csv_result()
    assert csv_result.value("source_population") == fx.CSV_SOURCE_POPULATION
    assert csv_result.value("excluded_population") == fx.CSV_EXCLUDED
    assert csv_result.value("reviewed_population") == fx.CSV_REVIEWED
    assert csv_result.value("decision_revoke") == fx.CSV_REVOKE


# ---------------------------------------------------------------------- 3
def test_3_every_fact_retains_provenance():
    for result in (_workbook_result(), _csv_result()):
        for fact in result.facts:
            assert fact.provenance, fact.key
            for p in fact.provenance:
                assert p.filename == result.filename
                assert p.sheet and p.locator

    result = _workbook_result()
    excluded = result.fact("source_population")
    assert [(p.sheet, p.locator) for p in excluded.provenance] == [
        (fx.SUMMARY_SHEET, "B10")]

    reviewed = result.fact("reviewed_population")
    assert {(p.sheet, p.locator) for p in reviewed.provenance} == {
        (fx.SUMMARY_SHEET, "B12"),
        (fx.DETAIL_SHEET, fx.DETAIL_RANGE),
    }

    decisions = result.fact("decision_revoke")
    assert any(p.locator == f"{fx.DETAIL_RANGE} column F" for p in decisions.provenance)

    populations = result.fact("identity_populations")
    assert populations.provenance[0].locator == f"{fx.DETAIL_RANGE} column C"

    # Checks carry the provenance of the numbers they reconciled.
    assert result.check(CHECK_DECISIONS).provenance


# ---------------------------------------------------------------------- 4
def test_4_population_arithmetic_is_validated():
    check = _csv_result().check(CHECK_POPULATION)
    assert check.state == SUPPORTED
    assert check.inputs == {
        "source_population": fx.CSV_SOURCE_POPULATION,
        "excluded_population": fx.CSV_EXCLUDED,
        "reviewed_population": fx.CSV_REVIEWED,
    }
    assert check.grounding == "EV-ACCESS-001/VR-002"
    assert "80 - excluded_population 5 = reviewed_population 75" in check.detail

    # The arithmetic really is arithmetic: break it and the check turns.
    facts = tuple(
        EvidenceFact(key, "label", value, "count", "stated",
                     (Provenance("f.csv", "s", "B1"),))
        for key, value in (("source_population", 80), ("excluded_population", 5),
                           ("reviewed_population", 74))
    )
    checks, _ = validate_user_access_review(facts)
    broken = next(c for c in checks if c.check_id == CHECK_POPULATION)
    assert broken.state == CONFLICT
    assert "difference -1" in broken.detail


# ---------------------------------------------------------------------- 5
def test_5_disposition_arithmetic_is_validated():
    for result, reviewed in ((_workbook_result(), fx.SUMMARY_REVIEWED),
                             (_csv_result(), fx.CSV_REVIEWED)):
        check = result.check(CHECK_DECISIONS)
        assert check.state == SUPPORTED, result.filename
        assert check.inputs["reviewed_population"] == reviewed
        assert f"= {reviewed}, matching reviewed_population {reviewed}" in check.detail

    facts = tuple(
        EvidenceFact(key, "label", value, "count", "stated",
                     (Provenance("f.csv", "s", "B1"),))
        for key, value in (("decision_retain", 60), ("decision_modify", 0),
                           ("decision_revoke", 9), ("decision_investigate", 5),
                           ("reviewed_population", 75))
    )
    checks, _ = validate_user_access_review(facts)
    broken = next(c for c in checks if c.check_id == CHECK_DECISIONS)
    assert broken.state == CONFLICT
    assert "difference -1" in broken.detail


# ---------------------------------------------------------------------- 6
def test_6_open_remediation_is_detected():
    # The worked example: 9 revocations, 8 completed -> 1 open.
    csv_result = _csv_result()
    check = csv_result.check(CHECK_REMEDIATION)
    assert check.state == PARTIALLY_SUPPORTED
    assert check.inputs["remediation_open_computed"] == fx.CSV_OPEN_REMEDIATION
    assert "leaving 1 open/unresolved remediation item(s)" in check.detail
    assert csv_result.value("remediation_open_computed") == fx.CSV_OPEN_REMEDIATION
    assert csv_result.fact("remediation_open_computed").derivation == "computed"

    # The workbook: 9 revoke + 8 modify flagged, 8 completed -> 9 open, which
    # matches the count the campaign itself states.
    result = _workbook_result()
    workbook_check = result.check(CHECK_REMEDIATION)
    assert workbook_check.state == PARTIALLY_SUPPORTED
    assert workbook_check.inputs["remediation_required"] == (
        fx.SUMMARY_REVOKE + fx.SUMMARY_MODIFY)
    assert result.value("remediation_open_computed") == fx.SUMMARY_REMEDIATION_OPEN

    # Closure evidence beyond the ticket is absent, and is reported as absent.
    assert result.check(CHECK_POST_CHANGE).state == PARTIALLY_SUPPORTED
    assert "no post-change system confirmation" in result.check(CHECK_POST_CHANGE).detail
    assert csv_result.check(CHECK_POST_CHANGE).state == MISSING

    # Open items stated by the artifact are surfaced, not judged.
    assert result.check("OPEN-ITEMS").state == PARTIALLY_SUPPORTED
    assert str(fx.SUMMARY_EXCEPTIONS) in result.check("OPEN-ITEMS").detail


# ---------------------------------------------------------------------- 7
def test_7_contradiction_is_surfaced_not_silently_resolved():
    result = _workbook_result()
    excluded = result.fact("excluded_population")
    assert excluded.conflict is True
    assert excluded.value is None, "a contradicted fact must not be given a value"

    values = {value for value, _ in excluded.conflicting_values}
    assert values == {fx.SUMMARY_EXCLUDED, fx.EXCLUSION_ROWS}
    locators = {(p.sheet, p.locator) for _, p in excluded.conflicting_values}
    assert locators == {(fx.SUMMARY_SHEET, fx.EXCLUDED_CELL),
                        (fx.EXCLUSIONS_SHEET, fx.EXCLUSIONS_RANGE)}

    # The dependent reconciliation refuses to run rather than picking a winner:
    # 120 - 8 = 112 would reconcile, 120 - 9 = 111 would not.
    population = result.check(CHECK_POPULATION)
    assert population.state == NEEDS_REVIEW
    assert "does not choose between them" in population.detail

    consistency = result.check(CHECK_CONSISTENCY)
    assert consistency.state == CONFLICT
    assert "excluded_population" in consistency.detail
    assert str(fx.SUMMARY_EXCLUDED) in consistency.detail
    assert str(fx.EXCLUSION_ROWS) in consistency.detail

    assert result.state == CONFLICT
    assert result.needs_review is True
    assert _csv_result().needs_review is False


# ---------------------------------------------------------------------- 8
def test_8_missing_evidence_is_never_a_control_failure():
    csv_result = _csv_result()
    missing = [c for c in csv_result.checks if c.state == MISSING]
    assert {c.check_id for c in missing} >= {CHECK_POST_CHANGE, CHECK_IDENTITY}
    for check in missing:
        assert "not a control failure" in check.detail

    # Missing pieces never drag the artifact below a partial picture.
    assert csv_result.state == PARTIALLY_SUPPORTED
    assert csv_result.check(CHECK_PERIOD).state == SUPPORTED

    # No result, anywhere, may assert a compliance verdict.
    for result in (_workbook_result(), csv_result,
                   analyze_evidence_file(fx.NON_REVIEW_FILENAME, fx.NON_REVIEW_CSV)):
        assert result.state in EVIDENCE_STATES
        blob = " ".join(
            [result.state, *result.notes]
            + [f"{c.state} {c.name} {c.detail}" for c in result.checks]
        ).upper()
        for banned in PROHIBITED_VERDICTS:
            assert banned not in blob, banned
        for word in ("PASS", "FAIL"):
            assert word not in blob.replace("FAILURE", "")

    # An unreadable upload is reported for review, not treated as a finding.
    broken = analyze_evidence_file("broken.xlsx", b"not a zip")
    assert broken.state == NEEDS_REVIEW and broken.evidence_type == UNCLASSIFIED
    assert not broken.checks


# ---------------------------------------------------------------------- 9
def test_9_extraction_is_separate_from_validation_and_pluggable():
    """A replacement extractor changes what is read, never what is concluded."""

    class StubModelExtractor:
        """Stands in for a future LLM-backed extractor."""

        evidence_type = USER_ACCESS_REVIEW
        source = "stub-model"

        def extract(self, workbook, classification):
            provenance = (Provenance(workbook.filename, "model", "n/a"),)
            return [
                EvidenceFact("source_population", "source population", 50, "count",
                             "stated", provenance),
                EvidenceFact("excluded_population", "excluded population", 5, "count",
                             "stated", provenance),
                EvidenceFact("reviewed_population", "reviewed population", 40, "count",
                             "stated", provenance),
            ]

    result = analyze_evidence_file(fx.CSV_FILENAME, fx.summary_csv(),
                                   extractor=StubModelExtractor())
    assert result.extractor == "stub-model"
    # DriftGuard, not the extractor, does the arithmetic - and catches it.
    assert result.check(CHECK_POPULATION).state == CONFLICT
    assert "difference -5" in result.check(CHECK_POPULATION).detail

    assert extractor_registry.get(USER_ACCESS_REVIEW).source == "deterministic-tabular"
    assert tuple(extractor_registry.registered_types()) == (USER_ACCESS_REVIEW,)


# --------------------------------------------------------------------- 10
def test_10_evidence_reaches_the_upload_results_page():
    payloads = [(fx.WORKBOOK_FILENAME, fx.campaign_workbook()),
                (fx.NON_REVIEW_FILENAME, fx.NON_REVIEW_CSV)]
    results = analyze_evidence(payloads)
    assert [r.evidence_type for r in results] == [USER_ACCESS_REVIEW, UNCLASSIFIED]

    from ingestion import extract_many

    documents, errors = extract_many(payloads)
    assessment = webapp.ANALYZER.analyze("Acme Cloud Inc.", documents, errors,
                                         demo=True, evidence=results)
    assert len(assessment.evidence) == 2
    webapp.DOC_ASSESSMENTS[assessment.assessment_id] = assessment

    status, text, _ = _call("GET", f"/doc-results/{assessment.assessment_id}")
    assert status == 200
    assert "Evidence QA" in text
    assert f"/evidence-report/{assessment.assessment_id}" in text
    # The CP006 document flow is untouched by the new section.
    assert "DriftGuard needs clarification" in text

    # The facts, states and provenance are carried into the Evidence QA report.
    status, report, _ = _call("GET", f"/evidence-report/{assessment.assessment_id}")
    assert status == 200
    assert USER_ACCESS_REVIEW in report
    assert "EV-ACCESS-001" in report
    assert fx.EXCLUDED_CELL in report and fx.EXCLUSIONS_RANGE in report
    assert "unresolved" in report
    assert "disagree" in report


# --------------------------------------------------------------------- 11
def test_11_unrecognised_decision_values_are_counted_not_dropped():
    """Every reviewed row is accounted for, including the ones nobody can read."""
    result = analyze_evidence_file(
        fx.EDGE_FILENAME, fx.edge_workbook(fx.UNRECOGNIZED_DECISION_ROWS))
    rows = len(fx.UNRECOGNIZED_DECISION_ROWS)
    assert result.value("reviewed_population") == rows
    assert result.value("decision_retain") == 1
    # "Excluded" is not a reviewer decision and a blank cell is not one either.
    assert result.value("decision_unrecognized") == 2

    # The invariant that makes "no row is dropped silently" checkable.
    recognised = sum(result.value(k) or 0 for k in
                     ("decision_retain", "decision_modify", "decision_revoke",
                      "decision_investigate"))
    assert recognised + result.value("decision_unrecognized") == rows

    # The unreadable rows are locatable, and their values are quoted verbatim.
    fact = result.fact("decision_unrecognized")
    assert fact.unit == "count" and fact.derivation == "counted"
    locator = fact.provenance[0].locator
    assert locator == "rows 3, 4 column D"
    assert "excluded" in fact.provenance[0].excerpt
    assert "(blank)" in fact.provenance[0].excerpt

    check = result.check(CHECK_DECISION_COVERAGE)
    assert check.state == NEEDS_REVIEW
    assert check.grounding == "EV-ACCESS-001/VR-002"      # existing rule, not invented
    assert "2 reviewed row(s) of 3" in check.detail
    assert locator in check.detail                        # names the count and the rows
    assert check.inputs["decision_unrecognized"] == 2

    # Clean artifacts say so, and an artifact with no decision column at all
    # reports the check as missing rather than inventing a zero.
    assert _workbook_result().check(CHECK_DECISION_COVERAGE).state == SUPPORTED
    assert _workbook_result().value("decision_unrecognized") == 0
    csv_check = _csv_result().check(CHECK_DECISION_COVERAGE)
    assert csv_check.state == MISSING
    assert _csv_result().fact("decision_unrecognized") is None
    assert "not a control failure" in csv_check.detail


# --------------------------------------------------------------------- 12
def test_12_unmapped_identity_values_do_not_become_identity_types():
    result = analyze_evidence_file(
        fx.EDGE_FILENAME, fx.edge_workbook(fx.UNMAPPED_IDENTITY_ROWS))
    populations = dict(result.value("identity_populations"))
    assert populations == {"employee": 1}
    # "Robot" matched no known type, so it is counted - not slugified into one.
    assert "robot" not in populations and "Robot" not in populations
    assert result.value("identity_unrecognized") == 1

    fact = result.fact("identity_unrecognized")
    assert fact.unit == "count"
    assert fact.provenance[0].locator == "row 3 column B"
    assert "robot" in fact.provenance[0].excerpt
    # The blank third row is an absent value, not an unrecognised one.
    assert sum(populations.values()) + fact.value == 2

    # The tidy fixtures map cleanly, so nothing is reported as unrecognised.
    assert _workbook_result().value("identity_unrecognized") == 0
    assert _csv_result().fact("identity_unrecognized") is None


# --------------------------------------------------------------------- 13
def test_13_post_change_confirmation_is_counted_per_row():
    """A confirmation column is not itself a confirmation."""
    empty = analyze_evidence_file(
        fx.EDGE_FILENAME, fx.edge_workbook(fx.EMPTY_CONFIRMATION_ROWS))
    assert empty.value("remediation_applicable_rows") == 2
    assert empty.value("remediation_confirmed_rows") == 0
    assert empty.value("remediation_unconfirmed_rows") == 2
    check = empty.check(CHECK_POST_CHANGE)
    assert check.state == MISSING
    assert "0 of 2" in check.detail
    assert "not a control failure" in check.detail

    partial = analyze_evidence_file(
        fx.EDGE_FILENAME, fx.edge_workbook(fx.PARTIAL_CONFIRMATION_ROWS))
    assert partial.value("remediation_applicable_rows") == 2
    assert partial.value("remediation_confirmed_rows") == 1
    assert partial.value("remediation_unconfirmed_rows") == 1
    partial_check = partial.check(CHECK_POST_CHANGE)
    assert partial_check.state == PARTIALLY_SUPPORTED
    assert "1 of 2" in partial_check.detail
    # The unconfirmed row is a timestamp, which is not read as an affirmation,
    # and the row it sits in can be found.
    unconfirmed = partial.fact("remediation_unconfirmed_rows")
    assert unconfirmed.provenance[0].locator == "row 4 column G"
    assert "2026-10-07" in unconfirmed.provenance[0].excerpt

    # Nothing remediated: there is nothing for a confirmation to cover.
    none_applicable = analyze_evidence_file(
        fx.EDGE_FILENAME, fx.edge_workbook(fx.NO_REMEDIATION_ROWS))
    assert none_applicable.value("remediation_applicable_rows") == 0
    assert none_applicable.check(CHECK_POST_CHANGE).state == SUPPORTED

    # Every applicable row confirmed, on the fully reconciled campaign.
    clean = analyze_evidence_file(fx.CLEAN_FILENAME, fx.clean_workbook())
    assert clean.value("remediation_applicable_rows") == (
        fx.CLEAN_MODIFY + fx.CLEAN_REVOKE)
    assert clean.value("remediation_confirmed_rows") == (
        fx.CLEAN_MODIFY + fx.CLEAN_REVOKE)
    assert clean.check(CHECK_POST_CHANGE).state == SUPPORTED

    # The old boolean fact is gone: presence of a column proves nothing.
    for result in (empty, partial, clean):
        assert result.fact("post_change_confirmation") is None

    # No confirmation column at all still reports what is absent as absent.
    assert _workbook_result().check(CHECK_POST_CHANGE).state == PARTIALLY_SUPPORTED
    assert _csv_result().check(CHECK_POST_CHANGE).state == MISSING


# --------------------------------------------------------------------- 14
def test_14_real_customer_export_is_read_without_invention():
    """The committed customer-shaped export: detail rows only, untidy values."""
    result = analyze_evidence_file(fx.REAL_FILENAME, fx.real_workbook())
    assert result.evidence_type == USER_ACCESS_REVIEW
    assert result.value("reviewed_population") == 5

    # Row 6 reads "Excluded", which is a scope statement and not a decision.
    assert result.value("decision_unrecognized") == 1
    coverage = result.check(CHECK_DECISION_COVERAGE)
    assert coverage.state == NEEDS_REVIEW
    assert "row 6 column D" in coverage.detail

    # Two identity values match no known type and are counted, not invented.
    assert result.value("identity_unrecognized") == 2
    populations = dict(result.value("identity_populations"))
    for invented in ("aarav.shah", "svc_backup_prod01"):
        assert invented not in populations

    # Four rows record remediation; not one carries a value DriftGuard reads as
    # a confirmation, so closure evidence is reported as missing rather than as
    # present because a column exists.
    assert result.value("remediation_applicable_rows") == 4
    assert result.value("remediation_confirmed_rows") == 0
    confirmation = result.check(CHECK_POST_CHANGE)
    assert confirmation.state == MISSING
    assert "0 of 4" in confirmation.detail
    assert "not a control failure" in confirmation.detail

    # Every fact keeps its provenance, and nothing asserts a verdict.
    for fact in result.facts:
        assert fact.provenance and all(p.locator for p in fact.provenance)
    blob = " ".join([result.state, *result.notes]
                    + [f"{c.state} {c.name} {c.detail}" for c in result.checks]).upper()
    for banned in PROHIBITED_VERDICTS:
        assert banned not in blob, banned


TESTS = [
    test_1_file_is_classified_as_user_access_review,
    test_2_structured_facts_are_extracted,
    test_3_every_fact_retains_provenance,
    test_4_population_arithmetic_is_validated,
    test_5_disposition_arithmetic_is_validated,
    test_6_open_remediation_is_detected,
    test_7_contradiction_is_surfaced_not_silently_resolved,
    test_8_missing_evidence_is_never_a_control_failure,
    test_9_extraction_is_separate_from_validation_and_pluggable,
    test_10_evidence_reaches_the_upload_results_page,
    test_11_unrecognised_decision_values_are_counted_not_dropped,
    test_12_unmapped_identity_values_do_not_become_identity_types,
    test_13_post_change_confirmation_is_counted_per_row,
    test_14_real_customer_export_is_read_without_invention,
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
