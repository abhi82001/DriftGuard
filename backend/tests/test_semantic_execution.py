#!/usr/bin/env python3
"""Tests for the semantic evaluator execution layer (Checkpoint 004).

These tests exercise the EXECUTION BOUNDARY, not the validator internals
(already covered by test_semantic_contract.py). Each case drives a scripted
stub evaluator - a test double that returns a preset result and performs no
reasoning whatsoever - through SemanticEvaluationRunner and asserts the runner
either returns a validated result or fails closed.

Real knowledge is used throughout: QN-ACCESS-001-Q09 / SEMCOND-0001 /
FND-CRYPTO-001.

Run:  python backend/tests/run_tests.py
   or python backend/tests/test_semantic_execution.py
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from evaluation.engine import (  # noqa: E402
    EVAL_DETERMINISTIC,
    OUTCOME_FIRED,
    OUTCOME_SEMANTIC_REQUIRED,
    EvaluationEngine,
)
from evaluation.execution import (  # noqa: E402
    SemanticEvaluationRunner,
    SemanticExecutionError,
    run_semantic_evaluation,
)
from evaluation.semantic import (  # noqa: E402
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluator,
    SemanticRequestError,
    SemanticResultValidationError,
    SemanticVerdict,
)

QN = "QN-ACCESS-001"
Q_SEM = "QN-ACCESS-001-Q09"       # free-text, semantic via SEMCOND-0001
Q_DET = "QN-ACCESS-001-Q01"       # single_select, deterministic
SEMCOND = "SEMCOND-0001"
AUTHORIZED_FINDING = "FND-CRYPTO-001"
ANSWER = "We encrypt the primary database."


def _engine() -> EvaluationEngine:
    return EvaluationEngine.from_repository()


# ------------------------------------------------------------- test doubles
class ScriptedEvaluator:
    """Test-only stub: returns a caller-supplied result, built from overrides.

    It performs NO semantic reasoning. Its only job is to let a test place
    arbitrary (including hostile) output on the untrusted side of the boundary.
    """

    def __init__(self, **overrides) -> None:
        self.overrides = overrides
        self.seen: list[SemanticEvaluationRequest] = []

    def evaluate(self, request: SemanticEvaluationRequest) -> SemanticEvaluationResult:
        self.seen.append(request)
        base = dict(
            result_id="SEMRES-TEST-0004",
            condition_id=request.condition_id,
            question_id=request.question_id,
            assessment=SemanticVerdict.INSUFFICIENT.value,
            confidence=0.5,
            present_elements=("SE-001",),
            missing_elements=("SE-002", "SE-003"),
            reason_codes=("element_not_mentioned",),
            needs_human_review=True,
            indicates_finding=request.indicates_finding,
        )
        base.update(self.overrides)
        return SemanticEvaluationResult(**base)


class RaisingEvaluator:
    """Test-only stub that fails the way a broken provider client would."""

    def evaluate(self, request: SemanticEvaluationRequest) -> SemanticEvaluationResult:
        raise RuntimeError("provider client exploded")


class WrongTypeEvaluator:
    """Test-only stub that returns something that is not a result object."""

    def evaluate(self, request: SemanticEvaluationRequest):
        return {"assessment": "SUPPORTED", "confidence": 1.0}


def _run(**overrides) -> SemanticEvaluationResult:
    return SemanticEvaluationRunner(_engine().knowledge, ScriptedEvaluator(**overrides)).run(
        QN, Q_SEM, ANSWER
    )


def _expect_rejected(name: str, **overrides) -> None:
    try:
        _run(**overrides)
    except SemanticResultValidationError:
        return
    raise AssertionError(f"{name} was not rejected at the execution boundary")


# ---------------------------------------------------------------------- 1
def test_1_valid_semantic_evaluation_succeeds():
    """End-to-end: build -> evaluate -> validate -> validated result."""
    evaluator = ScriptedEvaluator()
    runner = SemanticEvaluationRunner(_engine().knowledge, evaluator)
    out = runner.run(QN, Q_SEM, ANSWER)

    assert isinstance(out, SemanticEvaluationResult)
    assert out.condition_id == SEMCOND
    assert out.question_id == Q_SEM
    assert out.indicates_finding == AUTHORIZED_FINDING
    assert out.assessment in {v.value for v in SemanticVerdict}

    # The evaluator only ever saw a knowledge-grounded request; it did not get
    # to choose the condition, question, finding or expected elements.
    assert len(evaluator.seen) == 1
    req = evaluator.seen[0]
    assert req.condition_id == SEMCOND
    assert req.question_id == Q_SEM
    assert req.indicates_finding == AUTHORIZED_FINDING
    assert req.element_ids == {"SE-001", "SE-002", "SE-003"}
    assert req.answer_text == ANSWER

    # The stub satisfies the provider-independent Protocol.
    assert isinstance(evaluator, SemanticEvaluator)

    # The convenience wrapper takes the same path.
    again = run_semantic_evaluation(_engine().knowledge, ScriptedEvaluator(), QN, Q_SEM, ANSWER)
    assert again.to_dict() == out.to_dict()


# ---------------------------------------------------------------------- 2
def test_2_invented_finding_rejected_by_runner():
    _expect_rejected("invented finding", indicates_finding="FND-DOES-NOT-EXIST-999")


# ---------------------------------------------------------------------- 3
def test_3_mismatched_condition_or_question_rejected_by_runner():
    _expect_rejected("mismatched condition_id", condition_id="SEMCOND-0002")
    _expect_rejected("mismatched question_id", question_id=Q_DET)


# ---------------------------------------------------------------------- 4
def test_4_invalid_verdict_rejected_by_runner():
    _expect_rejected("invalid verdict", assessment="MOSTLY_FINE")


# ---------------------------------------------------------------------- 5
def test_5_ungrounded_element_rejected_by_runner():
    _expect_rejected("ungrounded element", missing_elements=("SE-002", "SE-999"))


# ---------------------------------------------------------------------- 6
def test_6_invalid_confidence_rejected_by_runner():
    _expect_rejected("out-of-range confidence", confidence=1.4)


# ---------------------------------------------------------------------- 7
def test_7_prohibited_compliance_conclusion_rejected_by_runner():
    # Smuggled into free-text notes rather than the verdict field.
    _expect_rejected(
        "prohibited compliance conclusion",
        notes=("Overall the organization is COMPLIANT with SOC 2.",),
    )


# ---------------------------------------------------------------------- 8
def test_8_runner_fails_closed_on_broken_evaluator():
    knowledge = _engine().knowledge

    for evaluator, label in ((RaisingEvaluator(), "raising"), (WrongTypeEvaluator(), "wrong-type")):
        try:
            SemanticEvaluationRunner(knowledge, evaluator).run(QN, Q_SEM, ANSWER)
        except SemanticExecutionError:
            continue
        raise AssertionError(f"{label} evaluator did not fail closed")

    # An object that is not an evaluator at all is refused at construction.
    try:
        SemanticEvaluationRunner(knowledge, object())
    except SemanticExecutionError:
        pass
    else:
        raise AssertionError("non-evaluator was accepted as an evaluator")


# ---------------------------------------------------------------------- 9
def test_9_deterministic_question_cannot_be_executed_semantically():
    try:
        SemanticEvaluationRunner(_engine().knowledge, ScriptedEvaluator()).run(QN, Q_DET, "No")
    except SemanticRequestError:
        return
    raise AssertionError("deterministic Q01 was run through the semantic evaluator")


# --------------------------------------------------------------------- 10
def test_10_deterministic_evaluation_unchanged():
    """Checkpoint 002 behaviour is untouched by the execution layer."""
    engine = _engine()

    det = engine.evaluate_question(QN, Q_DET, "No")
    assert det.evaluation_mode == EVAL_DETERMINISTIC
    assert det.outcome == OUTCOME_FIRED
    assert det.any_fired is True

    # The free-text question still reaches the semantic boundary without any
    # verdict being guessed by the deterministic engine.
    sem = engine.evaluate_question(QN, Q_SEM, ANSWER)
    assert sem.outcome == OUTCOME_SEMANTIC_REQUIRED
    assert all(r.condition_fired is None for r in sem.results)

    # Running the semantic layer does not mutate the deterministic outcome.
    SemanticEvaluationRunner(engine.knowledge, ScriptedEvaluator()).run(QN, Q_SEM, ANSWER)
    assert engine.evaluate_question(QN, Q_DET, "No").to_dict() == det.to_dict()


TESTS = [
    test_1_valid_semantic_evaluation_succeeds,
    test_2_invented_finding_rejected_by_runner,
    test_3_mismatched_condition_or_question_rejected_by_runner,
    test_4_invalid_verdict_rejected_by_runner,
    test_5_ungrounded_element_rejected_by_runner,
    test_6_invalid_confidence_rejected_by_runner,
    test_7_prohibited_compliance_conclusion_rejected_by_runner,
    test_8_runner_fails_closed_on_broken_evaluator,
    test_9_deterministic_question_cannot_be_executed_semantically,
    test_10_deterministic_evaluation_unchanged,
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
