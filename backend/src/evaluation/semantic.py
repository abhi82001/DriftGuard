#!/usr/bin/env python3
"""DriftGuard provider-independent semantic evaluation contract (Checkpoint 003).

This module defines the boundary a future semantic evaluator must cross. It does
NOT reason, call any model, or reach the network. It only:

  * turns a deterministic SEMANTIC_EVALUATION_REQUIRED into a grounded request
    built from real knowledge (build_semantic_request);
  * declares a provider-independent SemanticEvaluator interface;
  * validates untrusted model output against the knowledge that grounds it
    (validate_semantic_result), so a model can never smuggle in a finding,
    verdict, or reference the knowledge base did not authorize.

Verdict vocabulary and result fields are taken verbatim from
knowledge/soc2/schemas/semantic_evaluation_result.schema.json. Nothing here
invents a parallel knowledge model: requests are populated from the real
semantic_condition record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

from .engine import EngineError, KnowledgeBase

# --------------------------------------------------------------- vocabularies
# Mirrors semantic_evaluation_result.schema.json (assessment enum). Not
# redefined or extended: these are the only permitted verdicts.
class SemanticVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"
    UNDETERMINED = "UNDETERMINED"


# Mirrors the reason_codes enum in the same schema.
REASON_CODES = frozenset({
    "element_not_mentioned",
    "element_ambiguous",
    "answer_too_brief",
    "answer_off_topic",
    "conflicting_statements",
    "low_confidence",
})

# Mirrors x-prohibited-verdicts: values a result must never carry anywhere.
PROHIBITED_VERDICTS = frozenset({
    "SOC2_FAILED", "SOC2_PASSED", "COMPLIANT", "NON_COMPLIANT", "CERTIFIED",
    "AUDIT_OPINION", "QUALIFIED_OPINION", "UNQUALIFIED_OPINION",
})


# ------------------------------------------------------------------- errors
class SemanticError(EngineError):
    """Base for semantic-contract failures (aligns with the engine hierarchy)."""


class SemanticRequestError(SemanticError):
    """A semantic request could not be built from the given knowledge."""


class SemanticResultValidationError(SemanticError):
    """Untrusted model output failed validation against grounding knowledge."""


# ------------------------------------------------------------------- request
@dataclass(frozen=True)
class ExpectedElement:
    """One discrete thing an answer must evidence, copied from the record."""
    element_id: str
    description: str
    required: bool


@dataclass(frozen=True)
class SemanticEvaluationRequest:
    """Immutable, grounded input for one semantic evaluation.

    Every field is copied from the real semantic_condition record (plus the
    free-text answer under evaluation). A future evaluator receives only this;
    it never gets to choose the question, condition, finding, or elements.
    """
    condition_id: str
    question_id: str
    indicates_finding: str            # the ONLY finding this condition authorizes
    source_condition: str             # original prose, verbatim
    fires_when: str
    expected_elements: tuple[ExpectedElement, ...]
    answer_text: str

    @property
    def element_ids(self) -> frozenset[str]:
        return frozenset(e.element_id for e in self.expected_elements)

    def to_dict(self) -> dict:
        return {
            "condition_id": self.condition_id,
            "question_id": self.question_id,
            "indicates_finding": self.indicates_finding,
            "source_condition": self.source_condition,
            "fires_when": self.fires_when,
            "expected_elements": [
                {"element_id": e.element_id, "description": e.description, "required": e.required}
                for e in self.expected_elements
            ],
            "answer_text": self.answer_text,
        }


# -------------------------------------------------------------------- result
@dataclass(frozen=True)
class SemanticEvaluationResult:
    """Immutable result aligned with semantic_evaluation_result.schema.json.

    `indicates_finding` is optional: a future evaluator may attach the finding
    it believes is signalled, but validate_semantic_result confirms it is the
    one the semantic condition authorizes and rejects anything else.
    """
    result_id: str
    condition_id: str
    question_id: str
    assessment: str                       # a SemanticVerdict value
    confidence: float
    present_elements: tuple[str, ...]
    missing_elements: tuple[str, ...]
    reason_codes: tuple[str, ...]
    needs_human_review: bool
    indicates_finding: Optional[str] = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "record_type": "semantic_evaluation_result",
            "result_id": self.result_id,
            "condition_id": self.condition_id,
            "question_id": self.question_id,
            "assessment": self.assessment,
            "confidence": self.confidence,
            "present_elements": list(self.present_elements),
            "missing_elements": list(self.missing_elements),
            "reason_codes": list(self.reason_codes),
            "needs_human_review": self.needs_human_review,
            "indicates_finding": self.indicates_finding,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------- interface
@runtime_checkable
class SemanticEvaluator(Protocol):
    """Provider-independent semantic evaluator. No implementation lives here.

    A concrete evaluator (a future LLM-backed one, a human-in-the-loop one, a
    stub) implements evaluate(); its output must still pass
    validate_semantic_result before anything downstream trusts it.
    """

    def evaluate(self, request: SemanticEvaluationRequest) -> SemanticEvaluationResult:
        ...


# ------------------------------------------------------------------- builder
def build_semantic_request(
    knowledge: KnowledgeBase,
    questionnaire_id: str,
    question_id: str,
    answer_text: str,
) -> SemanticEvaluationRequest:
    """Build a grounded request from real DriftGuard knowledge.

    Only a genuinely semantic question can produce a request: the question must
    carry a gap signal with a semantic_condition_id, and that semantic condition
    must resolve to a real record. A deterministic question (Q01) has no such
    signal and is rejected.
    """
    _questionnaire, question = knowledge.get_question(questionnaire_id, question_id)

    sem_id = None
    for gap in question.get("gap_signals", []):
        if gap.get("semantic_condition_id"):
            sem_id = gap["semantic_condition_id"]
            break
    if sem_id is None:
        raise SemanticRequestError(
            f"question {question_id!r} has no semantic_condition_id gap signal; "
            f"it is not a semantic question and cannot be evaluated semantically"
        )

    condition = knowledge.get_semantic_condition(sem_id)  # raises if unknown

    # Grounding sanity check: the condition must belong to this question.
    if condition.get("question_id") != question_id:
        raise SemanticRequestError(
            f"semantic condition {sem_id!r} is for question "
            f"{condition.get('question_id')!r}, not {question_id!r}"
        )

    elements = tuple(
        ExpectedElement(e["element_id"], e["description"], bool(e["required"]))
        for e in condition["expected_elements"]
    )
    return SemanticEvaluationRequest(
        condition_id=condition["condition_id"],
        question_id=condition["question_id"],
        indicates_finding=condition["indicates_finding"],
        source_condition=condition["source_condition"],
        fires_when=condition["fires_when"],
        expected_elements=elements,
        answer_text=answer_text,
    )


# ----------------------------------------------------------------- validator
def validate_semantic_result(
    result: SemanticEvaluationResult,
    request: SemanticEvaluationRequest,
    known_finding_ids: Optional[set[str]] = None,
) -> SemanticEvaluationResult:
    """Validate untrusted evaluator output against the grounding request.

    Returns the result on success; raises SemanticResultValidationError on any
    violation. A model may never assert an arbitrary compliance conclusion,
    reference a different condition/question, or attach a finding the semantic
    condition did not authorize.
    """
    # Verdict must be one of the schema-defined values.
    valid_verdicts = {v.value for v in SemanticVerdict}
    if result.assessment not in valid_verdicts:
        raise SemanticResultValidationError(
            f"invalid verdict {result.assessment!r}; permitted: {sorted(valid_verdicts)}"
        )

    # No prohibited verdict may appear anywhere in the record.
    blob = str(result.to_dict()).upper()
    for banned in PROHIBITED_VERDICTS:
        if banned in blob:
            raise SemanticResultValidationError(f"result carries prohibited verdict {banned!r}")

    # Identity must match the grounding request.
    if result.condition_id != request.condition_id:
        raise SemanticResultValidationError(
            f"condition_id mismatch: result {result.condition_id!r} != "
            f"request {request.condition_id!r}"
        )
    if result.question_id != request.question_id:
        raise SemanticResultValidationError(
            f"question_id mismatch: result {result.question_id!r} != "
            f"request {request.question_id!r}"
        )

    # Confidence must be a probability.
    if not isinstance(result.confidence, (int, float)) or not (0.0 <= result.confidence <= 1.0):
        raise SemanticResultValidationError(
            f"confidence must be a number in [0, 1], got {result.confidence!r}"
        )

    # reason_codes must be non-empty and drawn from the controlled vocabulary.
    if not result.reason_codes:
        raise SemanticResultValidationError("reason_codes must not be empty")
    for rc in result.reason_codes:
        if rc not in REASON_CODES:
            raise SemanticResultValidationError(f"unknown reason_code {rc!r}")

    # Element references must be grounded in the request and not conflict.
    allowed = request.element_ids
    for e in result.present_elements:
        if e not in allowed:
            raise SemanticResultValidationError(f"present_elements references unknown element {e!r}")
    for e in result.missing_elements:
        if e not in allowed:
            raise SemanticResultValidationError(f"missing_elements references unknown element {e!r}")
    overlap = set(result.present_elements) & set(result.missing_elements)
    if overlap:
        raise SemanticResultValidationError(
            f"elements both present and missing: {sorted(overlap)}"
        )

    # Finding authorization: a result may only point at the finding the semantic
    # condition authorizes. This is where the finding/question relationship exists.
    if result.indicates_finding is not None:
        if known_finding_ids is not None and result.indicates_finding not in known_finding_ids:
            raise SemanticResultValidationError(
                f"result references unknown finding {result.indicates_finding!r}"
            )
        if result.indicates_finding != request.indicates_finding:
            raise SemanticResultValidationError(
                f"result asserts finding {result.indicates_finding!r} but semantic "
                f"condition only authorizes {request.indicates_finding!r}"
            )

    return result
