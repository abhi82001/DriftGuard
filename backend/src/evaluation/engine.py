#!/usr/bin/env python3
"""DriftGuard deterministic evaluation engine (Checkpoint 002).

This engine executes the mechanics of questionnaire gap-signal evaluation. It
does NOT define compliance meaning: the knowledge base does. The invariant is:

    KNOWLEDGE DEFINES REQUIREMENTS.
    ENGINE EVALUATES REQUIREMENTS.
    LLM MAY LATER INTERPRET TEXT.
    LLM MUST NEVER INVENT REQUIREMENTS.

Scope of Checkpoint 002:
  * load real questionnaire / question / finding records read-only;
  * evaluate the deterministic gap-signal grammar (version 1.0.0) that the
    knowledge base actually uses: operators equals, in, not_includes_all;
  * for free-text answers whose gap signals require semantic judgement, refuse
    to guess and report SEMANTIC_EVALUATION_REQUIRED instead.

No SOC 2 requirement, finding, or condition is hard-coded here. Unknown
operators, malformed conditions, mismatched answers, and broken knowledge
references all raise typed, explicit errors: nothing evaluates silently to
false, and nothing is silently repaired.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------- grammar
# Grammar version this engine evaluates. Mirrors the knowledge base's
# gap_signal_grammar_version and the operator table declared in the
# questionnaire schema / validate.py. The engine supports exactly the operators
# the knowledge base defines; it does not invent a second grammar.
GAP_GRAMMAR_VERSION = "1.0.0"

# operator -> (required field, operand key). Single source of the supported set.
_OPERATORS: dict[str, tuple[str, str]] = {
    "equals": ("answer.value", "value"),
    "in": ("answer.value", "values"),
    "not_includes_all": ("answer.values", "values"),
}

ENUMERATED_ANSWER_TYPES = {"single_select", "multi_select"}

# --------------------------------------------------------------------- outcomes
EVAL_DETERMINISTIC = "deterministic"
EVAL_SEMANTIC = "semantic"

OUTCOME_FIRED = "CONDITION_FIRED"
OUTCOME_NOT_FIRED = "CONDITION_NOT_FIRED"
OUTCOME_SEMANTIC_REQUIRED = "SEMANTIC_EVALUATION_REQUIRED"


# --------------------------------------------------------------------- errors
class EngineError(Exception):
    """Base class for all explicit, controlled engine failures."""


class KnowledgeError(EngineError):
    """A required knowledge record or cross-reference could not be resolved."""


class MalformedConditionError(EngineError):
    """A condition_expr is structurally invalid under grammar 1.0.0."""


class UnsupportedOperatorError(MalformedConditionError):
    """A condition_expr uses an operator the grammar does not define."""


class InvalidAnswerError(EngineError):
    """The supplied answer does not match the shape the condition requires."""


class UnsupportedGrammarVersionError(EngineError):
    """A questionnaire declares a gap-signal grammar version this engine does
    not support (or declares none where deterministic evaluation is attempted)."""


# --------------------------------------------------------- pure condition eval
def evaluate_condition_expr(expr: Any, answer: Any) -> bool:
    """Evaluate one gap-signal condition_expr against an answer.

    Pure and side-effect free: given identical inputs it always returns the
    same boolean. Raises an explicit typed error for anything it cannot
    evaluate. It never falls back to ``False`` for malformed, unknown, or
    unsupported input.
    """
    if not isinstance(expr, dict):
        raise MalformedConditionError("condition_expr must be an object")

    # Reject anything outside the grammar's four permitted keys up front, so a
    # smuggled or misspelled property is a hard failure rather than ignored.
    extra = set(expr) - {"operator", "field", "value", "values"}
    if extra:
        raise MalformedConditionError(
            f"condition_expr has unexpected propert{'y' if len(extra) == 1 else 'ies'}: "
            f"{sorted(extra)}"
        )

    operator = expr.get("operator")
    fld = expr.get("field")
    if operator is None:
        raise MalformedConditionError("condition_expr is missing 'operator'")
    if fld is None:
        raise MalformedConditionError("condition_expr is missing 'field'")
    if operator not in _OPERATORS:
        raise UnsupportedOperatorError(f"unsupported operator {operator!r}")

    required_field, operand_key = _OPERATORS[operator]
    if fld != required_field:
        raise MalformedConditionError(
            f"operator {operator!r} requires field {required_field!r}, got {fld!r}"
        )

    # Exactly the operand this operator uses must be present, and no other.
    other_key = "values" if operand_key == "value" else "value"
    if other_key in expr:
        raise MalformedConditionError(
            f"operator {operator!r} must not carry {other_key!r}"
        )
    if operand_key not in expr:
        raise MalformedConditionError(
            f"operator {operator!r} requires operand {operand_key!r}"
        )
    operand = expr[operand_key]

    if operand_key == "value":
        if not isinstance(operand, str):
            raise MalformedConditionError("'value' must be a string")
    else:
        if (not isinstance(operand, list) or not operand
                or not all(isinstance(v, str) for v in operand)):
            raise MalformedConditionError("'values' must be a non-empty array of strings")

    return _apply(operator, operand, fld, answer)


def _apply(operator: str, operand: Any, fld: str, answer: Any) -> bool:
    if fld == "answer.value":
        if not isinstance(answer, str):
            raise InvalidAnswerError(
                f"operator {operator!r} on {fld} expects a string answer, "
                f"got {type(answer).__name__}"
            )
        if operator == "equals":
            return answer == operand
        # operator == "in"
        return answer in operand

    # fld == "answer.values" -> operator is not_includes_all
    if not isinstance(answer, list) or not all(isinstance(v, str) for v in answer):
        raise InvalidAnswerError(
            f"operator {operator!r} on {fld} expects a list-of-strings answer, "
            f"got {type(answer).__name__}"
        )
    # Fires when at least one required option was NOT selected.
    return not all(v in answer for v in operand)


# ----------------------------------------------------------------- result model
@dataclass(frozen=True)
class SignalResult:
    """Result of evaluating one gap signal of a question against one answer."""
    condition: str                       # human-readable prose (explainability)
    evaluation_mode: str                 # deterministic | semantic
    outcome: str                         # OUTCOME_* token
    condition_fired: Optional[bool]      # None when semantic (never guessed)
    indicated_finding: str               # finding the signal points to (reference)
    finding_id: Optional[str]            # populated only when the condition fired
    severity: str
    confidence: Optional[str]
    condition_expr: Optional[dict]       # machine-readable form, when deterministic
    semantic_condition_id: Optional[str] # set when the signal is semantic
    trace: str                           # why this outcome was reached

    def to_dict(self) -> dict:
        return {
            "condition": self.condition,
            "evaluation_mode": self.evaluation_mode,
            "outcome": self.outcome,
            "condition_fired": self.condition_fired,
            "indicated_finding": self.indicated_finding,
            "finding_id": self.finding_id,
            "severity": self.severity,
            "confidence": self.confidence,
            "condition_expr": self.condition_expr,
            "semantic_condition_id": self.semantic_condition_id,
            "trace": self.trace,
        }


@dataclass(frozen=True)
class QuestionEvaluation:
    """Structured, traceable result of evaluating one question's gap signals.

    This object describes individual questionnaire conditions only. It carries
    no aggregate compliance verdict and must never be read as one.
    """
    questionnaire_id: str
    question_id: str
    input_answer: Any
    answer_type: str
    evaluation_mode: str
    outcome: str
    grammar_version: str
    results: tuple[SignalResult, ...] = field(default_factory=tuple)

    @property
    def any_fired(self) -> bool:
        return any(r.condition_fired for r in self.results)

    def to_dict(self) -> dict:
        return {
            "questionnaire_id": self.questionnaire_id,
            "question_id": self.question_id,
            "input_answer": self.input_answer,
            "answer_type": self.answer_type,
            "evaluation_mode": self.evaluation_mode,
            "outcome": self.outcome,
            "grammar_version": self.grammar_version,
            "results": [r.to_dict() for r in self.results],
        }


# --------------------------------------------------------------- knowledge base
def resolve_knowledge_root(start: Optional[Path] = None) -> Path:
    """Locate knowledge/soc2 by walking up from ``start`` (default: this file).

    No hard-coded absolute or sandbox paths: the root is discovered relative to
    the package location, or supplied explicitly by the caller.
    """
    here = (start or Path(__file__)).resolve()
    for base in [here, *here.parents]:
        candidate = base / "knowledge" / "soc2"
        if candidate.is_dir():
            return candidate
    raise KnowledgeError(
        "could not locate knowledge/soc2 relative to "
        f"{here}; pass knowledge_root explicitly"
    )


class KnowledgeBase:
    """Minimal read-only access to the questionnaire and finding records.

    Can be built from the real repository (``from_repository``) or from
    in-memory dicts (constructor), so negative tests never touch production
    knowledge files.
    """

    def __init__(
        self,
        questionnaires: dict[str, dict],
        finding_ids: set[str],
        semantic_condition_ids: Optional[set[str]] = None,
        semantic_conditions: Optional[dict[str, dict]] = None,
    ) -> None:
        self._questionnaires = questionnaires
        self._finding_ids = set(finding_ids)
        # Full semantic_condition records, indexed by condition_id, are kept
        # read-only so downstream layers can resolve the grounded record. The
        # id set is derived from both explicit ids and any loaded records.
        self._semantic_conditions = dict(semantic_conditions or {})
        ids = set(semantic_condition_ids or ())
        ids.update(self._semantic_conditions.keys())
        self._semantic_condition_ids = ids

    # -- construction --------------------------------------------------------
    @classmethod
    def from_repository(cls, knowledge_root: Optional[Path] = None) -> "KnowledgeBase":
        root = Path(knowledge_root) if knowledge_root is not None else resolve_knowledge_root()
        if not root.is_dir():
            raise KnowledgeError(f"knowledge root does not exist: {root}")

        # Duplicate IDs across files are a knowledge defect. We detect them
        # explicitly rather than letting dict overwrite or set de-duplication
        # silently hide the collision.
        questionnaires: dict[str, dict] = {}
        q_dir = root / "questionnaires"
        if not q_dir.is_dir():
            raise KnowledgeError(f"missing questionnaires directory: {q_dir}")
        for path in sorted(q_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            qid = doc.get("questionnaire_id")
            if not qid:
                raise KnowledgeError(f"questionnaire without id: {path}")
            if qid in questionnaires:
                raise KnowledgeError(f"duplicate questionnaire_id {qid!r} (also in {path})")
            questionnaires[qid] = doc

        finding_ids: set[str] = set()
        f_dir = root / "findings"
        if not f_dir.is_dir():
            raise KnowledgeError(f"missing findings directory: {f_dir}")
        for path in sorted(f_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            fid = doc.get("finding_id")
            if not fid:
                raise KnowledgeError(f"finding without id: {path}")
            if fid in finding_ids:
                raise KnowledgeError(f"duplicate finding_id {fid!r} (also in {path})")
            finding_ids.add(fid)

        # Semantic conditions are loaded read-only for reference integrity only:
        # the deterministic engine resolves their IDs but never evaluates them.
        semantic_conditions: dict[str, dict] = {}
        s_dir = root / "semantics"
        if not s_dir.is_dir():
            raise KnowledgeError(f"missing semantics directory: {s_dir}")
        for path in sorted(s_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.get("record_type") != "semantic_condition":
                continue  # e.g. semantic_evaluation_result example records
            cid = doc.get("condition_id")
            if not cid:
                raise KnowledgeError(f"semantic condition without condition_id: {path}")
            if cid in semantic_conditions:
                raise KnowledgeError(f"duplicate semantic condition_id {cid!r} (also in {path})")
            semantic_conditions[cid] = doc

        return cls(questionnaires, finding_ids, semantic_conditions=semantic_conditions)

    # -- lookups -------------------------------------------------------------
    def get_questionnaire(self, questionnaire_id: str) -> dict:
        doc = self._questionnaires.get(questionnaire_id)
        if doc is None:
            raise KnowledgeError(f"unknown questionnaire {questionnaire_id!r}")
        return doc

    def get_question(self, questionnaire_id: str, question_id: str) -> tuple[dict, dict]:
        questionnaire = self.get_questionnaire(questionnaire_id)
        for q in questionnaire.get("questions", []):
            if q.get("question_id") == question_id:
                return questionnaire, q
        raise KnowledgeError(
            f"unknown question {question_id!r} in questionnaire {questionnaire_id!r}"
        )

    def finding_exists(self, finding_id: str) -> bool:
        return finding_id in self._finding_ids

    def require_finding(self, finding_id: str) -> str:
        if finding_id not in self._finding_ids:
            raise KnowledgeError(f"gap signal references unknown finding {finding_id!r}")
        return finding_id

    def semantic_condition_exists(self, condition_id: str) -> bool:
        return condition_id in self._semantic_condition_ids

    def require_semantic_condition(self, condition_id: str) -> str:
        if condition_id not in self._semantic_condition_ids:
            raise KnowledgeError(
                f"gap signal references unknown semantic condition {condition_id!r}"
            )
        return condition_id

    def get_semantic_condition(self, condition_id: str) -> dict:
        """Return the full read-only semantic_condition record, or raise."""
        doc = self._semantic_conditions.get(condition_id)
        if doc is None:
            if condition_id in self._semantic_condition_ids:
                raise KnowledgeError(
                    f"semantic condition {condition_id!r} is known but its full "
                    f"record was not loaded"
                )
            raise KnowledgeError(f"unknown semantic condition {condition_id!r}")
        return doc


# ------------------------------------------------------------------- the engine
class EvaluationEngine:
    """Deterministic evaluator over real questionnaire gap signals."""

    def __init__(self, knowledge: KnowledgeBase) -> None:
        self.knowledge = knowledge

    @classmethod
    def from_repository(cls, knowledge_root: Optional[Path] = None) -> "EvaluationEngine":
        return cls(KnowledgeBase.from_repository(knowledge_root))

    def evaluate_question(
        self, questionnaire_id: str, question_id: str, answer: Any
    ) -> QuestionEvaluation:
        """Evaluate every gap signal of one question against one answer.

        For enumerated answer types the deterministic grammar is executed. For
        free-text (and other non-enumerated) answer types the engine refuses to
        judge and returns SEMANTIC_EVALUATION_REQUIRED: it never produces a
        guessed supported/not-supported verdict from free text.
        """
        questionnaire, question = self.knowledge.get_question(questionnaire_id, question_id)
        answer_type = question["answer_type"]
        gap_signals = question.get("gap_signals", [])

        if answer_type in ENUMERATED_ANSWER_TYPES:
            # Only evaluate deterministically if the questionnaire's declared
            # grammar version is one this engine actually supports. A different
            # or missing version means the condition_expr objects may not match
            # our assumptions, so we refuse rather than misread them.
            declared = questionnaire.get("gap_signal_grammar_version")
            if declared != GAP_GRAMMAR_VERSION:
                raise UnsupportedGrammarVersionError(
                    f"questionnaire {questionnaire_id!r} declares gap_signal_grammar_version "
                    f"{declared!r}; engine supports {GAP_GRAMMAR_VERSION!r}"
                )
            results = tuple(
                self._evaluate_deterministic_signal(question_id, answer_type, i, g, answer)
                for i, g in enumerate(gap_signals)
            )
            return QuestionEvaluation(
                questionnaire_id=questionnaire_id,
                question_id=question_id,
                input_answer=answer,
                answer_type=answer_type,
                evaluation_mode=EVAL_DETERMINISTIC,
                outcome=OUTCOME_FIRED if any(r.condition_fired for r in results) else OUTCOME_NOT_FIRED,
                grammar_version=GAP_GRAMMAR_VERSION,
                results=results,
            )

        # Non-enumerated answer type: semantic boundary. No guessing.
        results = tuple(
            self._semantic_boundary_signal(g) for g in gap_signals
        )
        return QuestionEvaluation(
            questionnaire_id=questionnaire_id,
            question_id=question_id,
            input_answer=answer,
            answer_type=answer_type,
            evaluation_mode=EVAL_SEMANTIC,
            outcome=OUTCOME_SEMANTIC_REQUIRED,
            grammar_version=GAP_GRAMMAR_VERSION,
            results=results,
        )

    # -- per-signal helpers --------------------------------------------------
    def _evaluate_deterministic_signal(
        self, question_id: str, answer_type: str, index: int, gap: dict, answer: Any
    ) -> SignalResult:
        indicated = gap["indicates_finding"]
        # Broken references fail explicitly, whether or not the signal fires.
        self.knowledge.require_finding(indicated)

        expr = gap.get("condition_expr")
        if expr is None:
            # An enumerated answer type without a machine-readable condition is a
            # knowledge-model defect. We surface it rather than silently skipping.
            raise KnowledgeError(
                f"{question_id}.gap_signals[{index}] has enumerated answer_type "
                f"{answer_type!r} but no condition_expr; cannot evaluate deterministically"
            )

        fired = evaluate_condition_expr(expr, answer)
        return SignalResult(
            condition=gap["condition"],
            evaluation_mode=EVAL_DETERMINISTIC,
            outcome=OUTCOME_FIRED if fired else OUTCOME_NOT_FIRED,
            condition_fired=fired,
            indicated_finding=indicated,
            finding_id=indicated if fired else None,
            severity=gap["severity"],
            confidence=gap.get("confidence"),
            condition_expr=expr,
            semantic_condition_id=None,
            trace=(
                f"grammar {GAP_GRAMMAR_VERSION}: applied "
                f"{expr['operator']} on {expr['field']} -> "
                f"{'fired' if fired else 'not fired'}; "
                + (f"indicates {indicated}" if fired else f"would indicate {indicated} if fired")
            ),
        )

    def _semantic_boundary_signal(self, gap: dict) -> SignalResult:
        indicated = gap["indicates_finding"]
        # Reference integrity still holds at the semantic boundary.
        self.knowledge.require_finding(indicated)
        sem_id = gap.get("semantic_condition_id")
        # If the signal names a semantic condition, verify it resolves. We do
        # NOT evaluate it: resolution is a reference-integrity check only.
        if sem_id is not None:
            self.knowledge.require_semantic_condition(sem_id)
        return SignalResult(
            condition=gap["condition"],
            evaluation_mode=EVAL_SEMANTIC,
            outcome=OUTCOME_SEMANTIC_REQUIRED,
            condition_fired=None,
            indicated_finding=indicated,
            finding_id=None,
            severity=gap["severity"],
            confidence=gap.get("confidence"),
            condition_expr=None,
            semantic_condition_id=sem_id,
            trace=(
                "free-text answer requires semantic judgement; deterministic "
                "engine does not guess. "
                + (f"decomposed by {sem_id}. " if sem_id else "")
                + "-> SEMANTIC_EVALUATION_REQUIRED"
            ),
        )
