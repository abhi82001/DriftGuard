#!/usr/bin/env python3
"""Tests for the provider-independent semantic evaluation contract (Checkpoint 003).

Uses REAL repository knowledge (QN-ACCESS-001-Q09 / SEMCOND-0001) to build
requests, and a hand-built fake result object to exercise validation. No model
is called; no semantic reasoning is implemented.

Run:  python backend/tests/run_tests.py
   or python backend/tests/test_semantic_contract.py
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from evaluation.engine import EvaluationEngine  # noqa: E402
from evaluation.semantic import (  # noqa: E402
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticRequestError,
    SemanticResultValidationError,
    SemanticVerdict,
    build_semantic_request,
    validate_semantic_result,
)

QN = "QN-ACCESS-001"
Q_SEM = "QN-ACCESS-001-Q09"       # free-text, semantic via SEMCOND-0001
Q_DET = "QN-ACCESS-001-Q01"       # single_select, deterministic
SEMCOND = "SEMCOND-0001"
AUTHORIZED_FINDING = "FND-CRYPTO-001"
KNOWN_FINDINGS = {"FND-CRYPTO-001", "FND-IAM-001"}


def _knowledge():
    return EvaluationEngine.from_repository().knowledge


def _real_request() -> SemanticEvaluationRequest:
    return build_semantic_request(_knowledge(), QN, Q_SEM, "We encrypt the primary database.")


def _valid_result(req: SemanticEvaluationRequest, **overrides) -> SemanticEvaluationResult:
    base = dict(
        result_id="SEMRES-TEST-0001",
        condition_id=req.condition_id,
        question_id=req.question_id,
        assessment=SemanticVerdict.INSUFFICIENT.value,
        confidence=0.5,
        present_elements=("SE-001",),
        missing_elements=("SE-002", "SE-003"),
        reason_codes=("element_not_mentioned",),
        needs_human_review=True,
        indicates_finding=AUTHORIZED_FINDING,
    )
    base.update(overrides)
    return SemanticEvaluationResult(**base)


# ---------------------------------------------------------------------- 1
def test_1_real_q09_semcond0001_request_builds():
    req = _real_request()
    assert req.condition_id == SEMCOND
    assert req.question_id == Q_SEM
    assert req.indicates_finding == AUTHORIZED_FINDING
    assert req.element_ids == {"SE-001", "SE-002", "SE-003"}
    assert req.source_condition  # grounded prose preserved


# ---------------------------------------------------------------------- 2
def test_2_deterministic_q01_cannot_become_semantic_request():
    try:
        build_semantic_request(_knowledge(), QN, Q_DET, "No")
    except SemanticRequestError:
        return
    raise AssertionError("deterministic Q01 wrongly produced a semantic request")


# ---------------------------------------------------------------------- 3
def test_3_invalid_verdict_rejected():
    req = _real_request()
    bad = _valid_result(req, assessment="SOC2_PASSED")
    try:
        validate_semantic_result(bad, req, known_finding_ids=KNOWN_FINDINGS)
    except SemanticResultValidationError:
        return
    raise AssertionError("invalid verdict was not rejected")


# ---------------------------------------------------------------------- 4
def test_4_invented_finding_rejected():
    req = _real_request()
    bad = _valid_result(req, indicates_finding="FND-INVENTED-999")
    try:
        validate_semantic_result(bad, req, known_finding_ids=KNOWN_FINDINGS)
    except SemanticResultValidationError:
        return
    raise AssertionError("invented finding was not rejected")


def test_4b_known_but_unauthorized_finding_rejected():
    # A real finding that this semantic condition does not authorize.
    req = _real_request()
    bad = _valid_result(req, indicates_finding="FND-IAM-001")
    try:
        validate_semantic_result(bad, req, known_finding_ids=KNOWN_FINDINGS)
    except SemanticResultValidationError:
        return
    raise AssertionError("unauthorized (but known) finding was not rejected")


# ---------------------------------------------------------------------- 5
def test_5_mismatched_condition_id_rejected():
    req = _real_request()
    bad = _valid_result(req, condition_id="SEMCOND-9999")
    try:
        validate_semantic_result(bad, req, known_finding_ids=KNOWN_FINDINGS)
    except SemanticResultValidationError:
        return
    raise AssertionError("mismatched condition_id was not rejected")


def test_5b_mismatched_question_id_rejected():
    req = _real_request()
    bad = _valid_result(req, question_id="QN-ACCESS-001-Q01")
    try:
        validate_semantic_result(bad, req, known_finding_ids=KNOWN_FINDINGS)
    except SemanticResultValidationError:
        return
    raise AssertionError("mismatched question_id was not rejected")


# ---------------------------------------------------------------------- 6
def test_6_valid_grounded_result_accepted():
    req = _real_request()
    good = _valid_result(req)
    out = validate_semantic_result(good, req, known_finding_ids=KNOWN_FINDINGS)
    assert out is good
    assert out.assessment in {v.value for v in SemanticVerdict}
    # No compliance verdict language leaks through.
    blob = str(out.to_dict()).upper()
    for banned in ("COMPLIANT", "CERTIFIED", "AUDIT_OPINION", "SOC2_PASSED"):
        assert banned not in blob


TESTS = [
    test_1_real_q09_semcond0001_request_builds,
    test_2_deterministic_q01_cannot_become_semantic_request,
    test_3_invalid_verdict_rejected,
    test_4_invented_finding_rejected,
    test_4b_known_but_unauthorized_finding_rejected,
    test_5_mismatched_condition_id_rejected,
    test_5b_mismatched_question_id_rejected,
    test_6_valid_grounded_result_accepted,
]


def run() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  ok    {t.__name__}")
        except Exception as e:  # noqa: BLE001 - harness reports every failure
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if failed else 'PASSED'}: {failed} failure(s)")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
