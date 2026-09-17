#!/usr/bin/env python3
"""DriftGuard minimal semantic evaluator execution layer (Checkpoint 004).

This module is the only place where a semantic evaluator is actually *run*. It
adds no reasoning, no provider, no network, no SDK: it is the safety harness
that sits between the knowledge base and some (future) evaluator.

Execution flow, in this order and no other:

    build_semantic_request(knowledge, ...)   # grounding comes from knowledge
        -> evaluator.evaluate(request)       # UNTRUSTED output
        -> validate_semantic_result(...)     # Checkpoint 003 validator
        -> validated result                  # only now may callers trust it

Trust rules enforced here (and nowhere duplicated):
  * The evaluator never chooses its own question, condition, finding or
    elements: it only ever sees a request built from real knowledge.
  * Evaluator output is untrusted until validate_semantic_result() returns. The
    runner never inspects, repairs, normalises or partially accepts it, and
    never re-implements any validator rule.
  * Fail closed. Any evaluator misbehaviour - raising, returning the wrong
    type, or returning output the validator rejects - produces an error, never
    a degraded or default verdict.
"""

from __future__ import annotations

from typing import Optional

from .engine import KnowledgeBase
from .semantic import (
    SemanticError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluator,
    build_semantic_request,
    validate_semantic_result,
)


class SemanticExecutionError(SemanticError):
    """An evaluator could not be executed safely; no result is produced.

    Raised when the evaluator raises, returns something that is not a
    SemanticEvaluationResult, or otherwise breaks the execution contract.
    Validation failures keep their own SemanticResultValidationError type so
    callers can tell "evaluator broken" from "evaluator output rejected".
    """


class SemanticEvaluationRunner:
    """Runs one provider-independent evaluator against real knowledge.

    The runner holds knowledge + an evaluator that satisfies the
    SemanticEvaluator Protocol. It is deliberately tiny: the whole point is
    that there is exactly one code path from knowledge to a validated result.
    """

    def __init__(
        self,
        knowledge: KnowledgeBase,
        evaluator: SemanticEvaluator,
        known_finding_ids: Optional[set[str]] = None,
    ) -> None:
        if not hasattr(evaluator, "evaluate") or not callable(evaluator.evaluate):
            raise SemanticExecutionError(
                f"evaluator {type(evaluator).__name__} does not implement "
                f"SemanticEvaluator.evaluate(request)"
            )
        self.knowledge = knowledge
        self.evaluator = evaluator
        # Default to the real finding ids the knowledge base loaded, so a
        # result can never reference a finding that does not exist.
        self.known_finding_ids = (
            set(known_finding_ids) if known_finding_ids is not None
            else set(knowledge.finding_ids)
        )

    # -- the single execution path ------------------------------------------
    def run(
        self, questionnaire_id: str, question_id: str, answer_text: str
    ) -> SemanticEvaluationResult:
        """Evaluate one free-text answer and return a validated result.

        Raises SemanticRequestError if the question is not semantic,
        SemanticExecutionError if the evaluator misbehaves, and
        SemanticResultValidationError if its output is not grounded.
        """
        request = build_semantic_request(
            self.knowledge, questionnaire_id, question_id, answer_text
        )
        return self.run_request(request)

    def run_request(
        self, request: SemanticEvaluationRequest
    ) -> SemanticEvaluationResult:
        """Run the evaluator on an already-grounded request."""
        if not isinstance(request, SemanticEvaluationRequest):
            raise SemanticExecutionError(
                f"request must be a SemanticEvaluationRequest, got "
                f"{type(request).__name__}"
            )

        try:
            raw = self.evaluator.evaluate(request)
        except SemanticError:
            # Already a typed, controlled semantic failure: propagate as-is.
            raise
        except Exception as exc:  # noqa: BLE001 - any provider fault fails closed
            raise SemanticExecutionError(
                f"evaluator {type(self.evaluator).__name__} raised "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if not isinstance(raw, SemanticEvaluationResult):
            raise SemanticExecutionError(
                f"evaluator {type(self.evaluator).__name__} returned "
                f"{type(raw).__name__}, expected SemanticEvaluationResult"
            )

        # Untrusted until this returns. No repair, no fallback verdict.
        return validate_semantic_result(
            raw, request, known_finding_ids=self.known_finding_ids
        )


def run_semantic_evaluation(
    knowledge: KnowledgeBase,
    evaluator: SemanticEvaluator,
    questionnaire_id: str,
    question_id: str,
    answer_text: str,
    known_finding_ids: Optional[set[str]] = None,
) -> SemanticEvaluationResult:
    """One-shot convenience wrapper around SemanticEvaluationRunner.run()."""
    return SemanticEvaluationRunner(
        knowledge, evaluator, known_finding_ids=known_finding_ids
    ).run(questionnaire_id, question_id, answer_text)
