#!/usr/bin/env python3
"""Tests for the DriftGuard deterministic evaluation engine (Checkpoint 002).

These tests use REAL repository knowledge for the positive and semantic-boundary
cases, and isolated in-memory fixtures for the negative cases. Production
knowledge files are never modified to create a failing condition.

Run:  python backend/tests/run_tests.py
   or python backend/tests/test_evaluation_engine.py
"""

import json
import sys
import tempfile
from pathlib import Path

# Make the engine importable without installation or PYTHONPATH setup.
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from evaluation.engine import (  # noqa: E402
    EVAL_DETERMINISTIC,
    EVAL_SEMANTIC,
    OUTCOME_NOT_FIRED,
    OUTCOME_SEMANTIC_REQUIRED,
    EvaluationEngine,
    InvalidAnswerError,
    KnowledgeBase,
    KnowledgeError,
    MalformedConditionError,
    UnsupportedGrammarVersionError,
    UnsupportedOperatorError,
    evaluate_condition_expr,
)

# Real repository records exercised below (unmodified):
#   QN-ACCESS-001-Q01  single_select, deterministic, fires FND-IAM-001
#   QN-ACCESS-001-Q04  multi_select, deterministic (not_includes_all)
#   QN-ACCESS-001-Q09  free-text, semantic via SEMCOND-0001
Q_DET = "QN-ACCESS-001-Q01"
Q_MULTI = "QN-ACCESS-001-Q04"
Q_SEM = "QN-ACCESS-001-Q09"
QN = "QN-ACCESS-001"


def _engine() -> EvaluationEngine:
    return EvaluationEngine.from_repository()


# --------------------------------------------------------------------- A + B
def test_A_condition_does_not_fire():
    """An answer that satisfies no deterministic gap condition -> not fired."""
    ev = _engine().evaluate_question(QN, Q_DET, "Yes, all listed systems")
    assert ev.evaluation_mode == EVAL_DETERMINISTIC
    assert ev.outcome == OUTCOME_NOT_FIRED
    assert ev.results, "expected at least one gap signal"
    assert all(r.condition_fired is False for r in ev.results)
    assert all(r.finding_id is None for r in ev.results)


def test_B_condition_fires_and_finding_is_traceable():
    """An answer that satisfies a deterministic gap condition -> fired, and the
    indicated finding resolves to a real finding record."""
    eng = _engine()
    ev = eng.evaluate_question(QN, Q_DET, "No")
    fired = [r for r in ev.results if r.condition_fired]
    assert fired, "expected at least one signal to fire"
    # The 'in [Some systems only, No]' signal points at FND-IAM-001.
    r = fired[0]
    assert r.finding_id == "FND-IAM-001"
    assert eng.knowledge.finding_exists(r.finding_id), "finding must be traceable"
    assert ev.any_fired


def test_B_multi_select_not_includes_all():
    """The not_includes_all operator on a real multi_select question."""
    eng = _engine()
    # Omitting privileged/service accounts fires the high-severity signal.
    ev = eng.evaluate_question(QN, Q_MULTI, ["Employees", "Contractors"])
    assert ev.any_fired
    fired = [r for r in ev.results if r.condition_fired]
    assert all(eng.knowledge.finding_exists(r.finding_id) for r in fired)

    # Selecting every population fires nothing.
    full = ["Employees", "Contractors", "Service accounts",
            "Shared accounts", "Privileged/administrative roles"]
    ev2 = eng.evaluate_question(QN, Q_MULTI, full)
    assert not ev2.any_fired


# ------------------------------------------------------------------------- C
def test_C_semantic_boundary_is_not_guessed():
    """A real free-text semantic question must return SEMANTIC_EVALUATION_REQUIRED
    and must never produce a guessed fired/not-fired verdict."""
    ev = _engine().evaluate_question(
        QN, Q_SEM, "We encrypt the primary database with AES-256."
    )
    assert ev.evaluation_mode == EVAL_SEMANTIC
    assert ev.outcome == OUTCOME_SEMANTIC_REQUIRED
    assert ev.results
    for r in ev.results:
        assert r.condition_fired is None, "engine must not guess a verdict"
        assert r.finding_id is None
        assert r.outcome == OUTCOME_SEMANTIC_REQUIRED
    # The representative semantic-condition decomposition is surfaced, not evaluated.
    assert any(r.semantic_condition_id == "SEMCOND-0001" for r in ev.results)


# ------------------------------------------------------------------------- D
def test_D_unknown_operator_fails_explicitly():
    expr = {"operator": "matches", "field": "answer.value", "value": "No"}
    try:
        evaluate_condition_expr(expr, "No")
    except UnsupportedOperatorError:
        return
    raise AssertionError("unknown operator did not raise UnsupportedOperatorError")


# ------------------------------------------------------------------------- E
def test_E_malformed_conditions_fail_explicitly():
    malformed = [
        "answer == 'No'",                                             # not an object
        {"field": "answer.value", "value": "No"},                    # missing operator
        {"operator": "equals", "field": "answer.value"},             # missing operand
        {"operator": "equals", "field": "answer.values", "value": "No"},   # wrong field
        {"operator": "equals", "field": "answer.value", "value": "No",
         "values": ["No"]},                                          # both operands
        {"operator": "equals", "field": "answer.value", "value": "No",
         "negate": True},                                            # extra property
        {"operator": "in", "field": "answer.value", "values": []},   # empty operand list
        {"operator": "in", "field": "answer.value", "values": "No"}, # operand wrong type
    ]
    for expr in malformed:
        try:
            evaluate_condition_expr(expr, "No")
        except MalformedConditionError:
            continue
        raise AssertionError(f"malformed condition did not raise: {expr!r}")


def test_E_mismatched_answer_shape_fails_explicitly():
    # single_select operator with a list answer, and vice versa.
    try:
        evaluate_condition_expr({"operator": "equals", "field": "answer.value", "value": "No"}, ["No"])
    except InvalidAnswerError:
        pass
    else:
        raise AssertionError("list answer to answer.value did not raise")

    try:
        evaluate_condition_expr(
            {"operator": "not_includes_all", "field": "answer.values", "values": ["A"]}, "A"
        )
    except InvalidAnswerError:
        pass
    else:
        raise AssertionError("string answer to answer.values did not raise")


# ------------------------------------------------------------------------- F
def test_F_missing_questionnaire_fails_explicitly():
    try:
        _engine().evaluate_question("QN-DOES-NOT-EXIST-001", "QN-DOES-NOT-EXIST-001-Q01", "x")
    except KnowledgeError:
        return
    raise AssertionError("missing questionnaire did not raise KnowledgeError")


def test_F_missing_question_fails_explicitly():
    try:
        _engine().evaluate_question(QN, "QN-ACCESS-001-Q99", "x")
    except KnowledgeError:
        return
    raise AssertionError("missing question did not raise KnowledgeError")


def test_F_broken_finding_reference_fails_explicitly():
    """Isolated in-memory fixture: a questionnaire whose gap signal points at a
    finding that does not exist. Production knowledge is untouched."""
    fixture_questionnaire = {
        "questionnaire_id": "QN-FIXTURE-001",
        "gap_signal_grammar_version": "1.0.0",
        "questions": [
            {
                "question_id": "QN-FIXTURE-001-Q01",
                "answer_type": "single_select",
                "options": ["Yes", "No"],
                "gap_signals": [
                    {
                        "condition": "answer == 'No'",
                        "condition_expr": {"operator": "equals", "field": "answer.value", "value": "No"},
                        "indicates_finding": "FND-DOES-NOT-EXIST-999",
                        "severity": "high",
                        "confidence": "high",
                    }
                ],
            }
        ],
    }
    kb = KnowledgeBase({"QN-FIXTURE-001": fixture_questionnaire}, finding_ids=set())
    eng = EvaluationEngine(kb)
    try:
        eng.evaluate_question("QN-FIXTURE-001", "QN-FIXTURE-001-Q01", "No")
    except KnowledgeError:
        return
    raise AssertionError("broken finding reference did not raise KnowledgeError")


# ------------------------------------- H: semantic reference integrity (new)
def test_H_unknown_semantic_condition_fails_explicitly():
    """Isolated in-memory fixture: a free-text gap signal names a
    semantic_condition_id that does not exist. The semantic-boundary path must
    verify it and raise KnowledgeError, without evaluating the condition."""
    fixture = {
        "questionnaire_id": "QN-FIXTURE-002",
        "gap_signal_grammar_version": "1.0.0",
        "questions": [
            {
                "question_id": "QN-FIXTURE-002-Q01",
                "answer_type": "text",
                "gap_signals": [
                    {
                        "condition": "answer omits something",
                        "semantic_condition_id": "SEMCOND-9999",
                        "indicates_finding": "FND-IAM-001",
                        "severity": "high",
                        "confidence": "medium",
                    }
                ],
            }
        ],
    }
    kb = KnowledgeBase(
        {"QN-FIXTURE-002": fixture},
        finding_ids={"FND-IAM-001"},
        semantic_condition_ids=set(),  # SEMCOND-9999 absent
    )
    eng = EvaluationEngine(kb)
    try:
        eng.evaluate_question("QN-FIXTURE-002", "QN-FIXTURE-002-Q01", "some free text")
    except KnowledgeError:
        return
    raise AssertionError("unknown semantic condition did not raise KnowledgeError")


def test_H_known_semantic_condition_resolves_against_repository():
    """The real Q09/SEMCOND-0001 pairing resolves (loader indexes semantics)."""
    eng = _engine()
    assert eng.knowledge.semantic_condition_exists("SEMCOND-0001")
    ev = eng.evaluate_question(QN, Q_SEM, "free text")
    assert any(r.semantic_condition_id == "SEMCOND-0001" for r in ev.results)
    assert all(r.condition_fired is None for r in ev.results)


# --------------------------------------- I: duplicate runtime IDs (new)
def _write_minimal_root(tmp: Path):
    """Build a minimal but valid on-disk knowledge root for loader tests."""
    (tmp / "questionnaires").mkdir(parents=True)
    (tmp / "findings").mkdir(parents=True)
    (tmp / "semantics").mkdir(parents=True)
    (tmp / "findings" / "f1.json").write_text(
        json.dumps({"record_type": "finding", "finding_id": "FND-X-001"}), encoding="utf-8"
    )
    (tmp / "semantics" / "s1.json").write_text(
        json.dumps({"record_type": "semantic_condition", "condition_id": "SEMCOND-1001"}),
        encoding="utf-8",
    )
    (tmp / "questionnaires" / "q1.json").write_text(
        json.dumps({"questionnaire_id": "QN-X-001", "questions": []}), encoding="utf-8"
    )
    # This clean root must load without error.
    KnowledgeBase.from_repository(tmp)


def test_I_duplicate_questionnaire_id_detected():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _write_minimal_root(tmp)
        (tmp / "questionnaires" / "q2.json").write_text(
            json.dumps({"questionnaire_id": "QN-X-001", "questions": []}), encoding="utf-8"
        )
        try:
            KnowledgeBase.from_repository(tmp)
        except KnowledgeError as e:
            assert "QN-X-001" in str(e)
            return
    raise AssertionError("duplicate questionnaire_id not detected")


def test_I_duplicate_finding_id_detected():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _write_minimal_root(tmp)
        (tmp / "findings" / "f2.json").write_text(
            json.dumps({"record_type": "finding", "finding_id": "FND-X-001"}), encoding="utf-8"
        )
        try:
            KnowledgeBase.from_repository(tmp)
        except KnowledgeError as e:
            assert "FND-X-001" in str(e)
            return
    raise AssertionError("duplicate finding_id not detected")


def test_I_duplicate_semantic_condition_id_detected():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _write_minimal_root(tmp)
        (tmp / "semantics" / "s2.json").write_text(
            json.dumps({"record_type": "semantic_condition", "condition_id": "SEMCOND-1001"}),
            encoding="utf-8",
        )
        try:
            KnowledgeBase.from_repository(tmp)
        except KnowledgeError as e:
            assert "SEMCOND-1001" in str(e)
            return
    raise AssertionError("duplicate semantic condition_id not detected")


# ---------------------------------- J: grammar-version compatibility (new)
def _det_fixture(grammar_version):
    q = {
        "questionnaire_id": "QN-FIXTURE-003",
        "questions": [
            {
                "question_id": "QN-FIXTURE-003-Q01",
                "answer_type": "single_select",
                "options": ["Yes", "No"],
                "gap_signals": [
                    {
                        "condition": "answer == 'No'",
                        "condition_expr": {"operator": "equals", "field": "answer.value", "value": "No"},
                        "indicates_finding": "FND-IAM-001",
                        "severity": "high",
                        "confidence": "high",
                    }
                ],
            }
        ],
    }
    if grammar_version is not None:
        q["gap_signal_grammar_version"] = grammar_version
    kb = KnowledgeBase({"QN-FIXTURE-003": q}, finding_ids={"FND-IAM-001"})
    return EvaluationEngine(kb)


def test_J_grammar_supported_1_0_0():
    # Real repository questionnaire declares 1.0.0 and evaluates fine.
    ev = _engine().evaluate_question(QN, Q_DET, "No")
    assert ev.grammar_version == "1.0.0"
    assert ev.any_fired
    # And the in-memory 1.0.0 fixture evaluates too.
    ev2 = _det_fixture("1.0.0").evaluate_question("QN-FIXTURE-003", "QN-FIXTURE-003-Q01", "No")
    assert ev2.any_fired


def test_J_grammar_unsupported_version_fails():
    try:
        _det_fixture("2.0.0").evaluate_question("QN-FIXTURE-003", "QN-FIXTURE-003-Q01", "No")
    except UnsupportedGrammarVersionError:
        return
    raise AssertionError("unsupported grammar version did not raise")


def test_J_grammar_missing_version_fails():
    try:
        _det_fixture(None).evaluate_question("QN-FIXTURE-003", "QN-FIXTURE-003-Q01", "No")
    except UnsupportedGrammarVersionError:
        return
    raise AssertionError("missing grammar version did not raise for deterministic evaluation")


# ------------------------------------------------------------------------- G
def test_G_determinism():
    eng = _engine()
    first = eng.evaluate_question(QN, Q_DET, "No").to_dict()
    for _ in range(5):
        assert eng.evaluate_question(QN, Q_DET, "No").to_dict() == first
    # Pure evaluator is stable too.
    expr = {"operator": "in", "field": "answer.value", "values": ["Some systems only", "No"]}
    assert all(evaluate_condition_expr(expr, "No") is True for _ in range(5))


# ---------------------------------------------------------- engine never opines
def test_engine_emits_no_compliance_verdict():
    import json
    ev = _engine().evaluate_question(QN, Q_DET, "No")
    blob = json.dumps(ev.to_dict()).upper()
    for banned in ("COMPLIANT", "SOC 2 COMPLIANT", "CERTIFIED", "PASSED", "AUDIT OPINION"):
        assert banned not in blob, f"result must not contain verdict language: {banned}"


TESTS = [
    test_A_condition_does_not_fire,
    test_B_condition_fires_and_finding_is_traceable,
    test_B_multi_select_not_includes_all,
    test_C_semantic_boundary_is_not_guessed,
    test_D_unknown_operator_fails_explicitly,
    test_E_malformed_conditions_fail_explicitly,
    test_E_mismatched_answer_shape_fails_explicitly,
    test_F_missing_questionnaire_fails_explicitly,
    test_F_missing_question_fails_explicitly,
    test_F_broken_finding_reference_fails_explicitly,
    test_H_unknown_semantic_condition_fails_explicitly,
    test_H_known_semantic_condition_resolves_against_repository,
    test_I_duplicate_questionnaire_id_detected,
    test_I_duplicate_finding_id_detected,
    test_I_duplicate_semantic_condition_id_detected,
    test_J_grammar_supported_1_0_0,
    test_J_grammar_unsupported_version_fails,
    test_J_grammar_missing_version_fails,
    test_G_determinism,
    test_engine_emits_no_compliance_verdict,
]


def run() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  ok    {t.__name__}")
        except Exception as e:  # noqa: BLE001 - test harness reports every failure
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if failed else 'PASSED'}: {failed} failure(s)")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
