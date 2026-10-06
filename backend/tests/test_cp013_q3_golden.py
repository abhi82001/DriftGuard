"""CP013 golden regression against the exact distributed Q3 XLSX."""
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from evidence import analyze_evidence_file, build_report
from evidence.temporal_review import review_recorded_confirmation_dates
from evidence.validation import CHECK_DECISION_COVERAGE, CHECK_REMEDIATION, CHECK_POST_CHANGE

FIXTURE = Path(__file__).parent / "fixtures" / "files" / "Q3_Access_Review.xlsx"


def _result():
    return analyze_evidence_file(FIXTURE.name, FIXTURE.read_bytes())


def test_exact_q3_golden_row_arithmetic_and_provenance():
    result = _result()
    expected = {
        "reviewed_population": 5, "decision_retain": 1, "decision_revoke": 2,
        "decision_investigate": 1, "decision_unrecognized": 1,
        "remediation_completed": 1, "remediation_open": 2,
        "remediation_open_computed": 1, "remediation_applicable_rows": 3,
        "remediation_confirmed_rows": 0, "remediation_recorded_confirmation_rows": 1,
        "remediation_unavailable_confirmation_rows": 1,
        "remediation_missing_confirmation_rows": 1,
        "remediation_unconfirmed_rows": 3,
    }
    for key, value in expected.items():
        assert result.value(key) == value, key
    assert result.value("remediation_confirmed_rows") + result.value("remediation_unconfirmed_rows") == result.value("remediation_applicable_rows")
    assert sum(result.value(key) for key in (
        "remediation_confirmed_rows", "remediation_recorded_confirmation_rows",
        "remediation_unavailable_confirmation_rows", "remediation_missing_confirmation_rows")) == 3
    rows = result.value("remediation_rows")
    assert [r[0] for r in rows] == [2, 3, 4, 5, 6]
    assert rows[-1][1] == "excluded"
    assert rows[-1][0] not in (3, 4, 5)  # exclusion note alone is not remediation activity
    assert rows[1][4] == "2026-10-07 08:52 utc"
    report = build_report(result)
    lines = {line.check_id: line for line in report.exceptions + report.reconciled}
    assert "row 6 column D" in lines[CHECK_DECISION_COVERAGE].detail
    assert "row 6" in str(lines[CHECK_DECISION_COVERAGE].provenance)
    assert "different populations" in lines[CHECK_REMEDIATION].headline
    assert "1 recorded evidence item(s)" in lines[CHECK_POST_CHANGE].headline
    assert "timestamp alone" in lines[CHECK_POST_CHANGE].headline.lower()


def test_q3_future_timestamp_requires_explicit_authoritative_cutoff():
    rows = _result().value("remediation_rows")
    flagged = review_recorded_confirmation_dates(rows, as_of=date(2026, 9, 30))
    assert len(flagged) == 1
    assert flagged[0]["row"] == 3 and flagged[0]["column"] == "H"
    assert flagged[0]["state"] == "NEEDS_REVIEW"
    assert review_recorded_confirmation_dates(rows, as_of=date(2026, 10, 8)) == ()
    assert review_recorded_confirmation_dates(rows, as_of=date(2026, 10, 7)) == ()


def test_q3_excluded_remains_unrecognized_without_approved_rule():
    result = _result()
    assert result.value("decision_unrecognized") == 1
    assert result.value("remediation_applicable_rows") == 3
