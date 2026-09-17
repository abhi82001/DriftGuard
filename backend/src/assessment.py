#!/usr/bin/env python3
"""Minimal MVP orchestration over the existing CP002-CP005 evaluation layers.

Deterministic questions go through the CP002 engine; semantic questions go
through CP003/CP004 with either the CP005 Claude adapter or, in demo mode, a
deterministic local stub that makes no network call. Findings and remediations
are read from existing knowledge records only.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluation.engine import (  # noqa: E402
    OUTCOME_FIRED,
    EvaluationEngine,
    resolve_knowledge_root,
)
from evaluation.execution import SemanticEvaluationRunner  # noqa: E402
from evaluation.providers.claude import ClaudeSemanticEvaluator  # noqa: E402
from evaluation.semantic import (  # noqa: E402
    SemanticError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticVerdict,
)

ENV_DEMO = "DRIFTGUARD_DEMO_MODE"

STATUS_NO_GAP = "NO_GAP_SIGNAL"
STATUS_GAP = "GAP_SIGNAL"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_SKIPPED = "NOT_ANSWERED"

_STOPWORDS = {
    "answer", "states", "state", "the", "that", "this", "with", "from", "which",
    "holding", "protected", "information", "encryption", "position", "storage",
    "describes", "names", "covers", "their", "there", "where", "also", "and",
    "for", "has", "have", "been", "were", "into", "over", "each", "when",
    "what", "whether", "about", "them", "these", "those", "some", "any",
}


def demo_mode_enabled() -> bool:
    return os.environ.get(ENV_DEMO, "").strip() not in {"", "0", "false", "False"}


# ------------------------------------------------------------- demo evaluator
class DemoSemanticEvaluator:
    """Deterministic local stand-in for a semantic evaluator. NOT a model.

    Marks an expected element present when a distinctive word of its own
    description appears in the answer text. Offline, repeatable, and labelled
    as DEMO everywhere it surfaces.
    """

    source = "demo-stub"

    def evaluate(self, request: SemanticEvaluationRequest) -> SemanticEvaluationResult:
        answer = request.answer_text.lower()
        present, missing = [], []
        for element in request.expected_elements:
            words = {
                w.strip(".,;:()").lower()
                for w in element.description.split()
                if len(w) > 4
            } - _STOPWORDS
            (present if any(w in answer for w in words) else missing).append(
                element.element_id
            )

        if missing:
            assessment = (
                SemanticVerdict.PARTIALLY_SUPPORTED.value if present
                else SemanticVerdict.INSUFFICIENT.value
            )
            reason_codes = ("element_not_mentioned",)
        else:
            assessment = SemanticVerdict.SUPPORTED.value
            reason_codes = ("low_confidence",)

        return SemanticEvaluationResult(
            result_id=f"SEMRES-DEMO-{uuid.uuid4().hex[:12].upper()}",
            condition_id=request.condition_id,
            question_id=request.question_id,
            assessment=assessment,
            confidence=0.5,
            present_elements=tuple(present),
            missing_elements=tuple(missing),
            reason_codes=reason_codes,
            needs_human_review=True,
            indicates_finding=request.indicates_finding if missing else None,
            notes=(
                "DEMO MODE: produced by a local deterministic keyword stub, "
                "not by any model. Requires human review.",
            ),
        )


# ------------------------------------------------------------------ knowledge
class MvpKnowledge:
    """Read-only questionnaire / finding / remediation view for the UI."""

    def __init__(self, knowledge_root: Optional[Path] = None) -> None:
        root = Path(knowledge_root) if knowledge_root else resolve_knowledge_root()
        self.engine = EvaluationEngine.from_repository(root)
        self.questionnaires = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((root / "questionnaires").glob("*.json"))
        ]
        self.findings = {
            d["finding_id"]: d
            for d in (
                json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((root / "findings").glob("*.json"))
            )
        }
        self.remediations = {
            d["remediation_id"]: d
            for d in (
                json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((root / "remediations").glob("*.json"))
            )
        }

    def question(self, questionnaire_id: str, question_id: str) -> dict:
        return self.engine.knowledge.get_question(questionnaire_id, question_id)[1]

    def finding_view(self, finding_id: str) -> Optional[dict]:
        rec = self.findings.get(finding_id)
        if rec is None:
            return None
        rems = [
            {
                "remediation_id": rid,
                "name": self.remediations[rid]["name"],
                "effort": self.remediations[rid].get("effort", ""),
            }
            for rid in rec.get("remediations", [])
            if rid in self.remediations
        ]
        return {
            "finding_id": finding_id,
            "name": rec.get("name", ""),
            "description": rec.get("description", ""),
            "severity": rec.get("default_severity", ""),
            "remediations": rems,
        }


# -------------------------------------------------------------------- results
@dataclass
class QuestionResult:
    questionnaire_id: str
    question_id: str
    text: str
    answer: Any
    mode: str                     # deterministic | semantic | none
    status: str
    detail: str = ""
    verdict: Optional[str] = None
    confidence: Optional[float] = None
    reason_codes: tuple[str, ...] = ()
    needs_review: bool = False
    findings: list[dict] = field(default_factory=list)
    source: str = ""


@dataclass
class Assessment:
    assessment_id: str
    vendor: str
    mode: str                     # DEMO | CLAUDE
    results: list[QuestionResult]

    @property
    def counts(self) -> dict:
        return {
            "answered": sum(1 for r in self.results if r.status != STATUS_SKIPPED),
            "gaps": sum(1 for r in self.results if r.status == STATUS_GAP),
            "needs_review": sum(1 for r in self.results if r.needs_review
                                or r.status == STATUS_NEEDS_REVIEW),
            "findings": len({f["finding_id"] for r in self.results for f in r.findings}),
        }


# --------------------------------------------------------------- orchestration
def _semantic_condition_id(question: dict) -> Optional[str]:
    for gap in question.get("gap_signals", []):
        if gap.get("semantic_condition_id"):
            return gap["semantic_condition_id"]
    return None


def run_assessment(
    knowledge: MvpKnowledge,
    vendor: str,
    answers: dict[tuple[str, str], Any],
    demo: Optional[bool] = None,
) -> Assessment:
    """Evaluate every answered question. Never raises for one bad answer."""
    demo = demo_mode_enabled() if demo is None else demo
    engine = knowledge.engine

    evaluator: Any = None
    evaluator_error = ""
    if demo:
        evaluator = DemoSemanticEvaluator()
    else:
        try:
            evaluator = ClaudeSemanticEvaluator()
        except Exception as exc:  # noqa: BLE001 - fail safe, not fatal
            evaluator_error = f"semantic evaluation unavailable: {exc}"
    runner = SemanticEvaluationRunner(engine.knowledge, evaluator) if evaluator else None
    source = "demo-stub" if demo else "claude"

    results: list[QuestionResult] = []
    for doc in knowledge.questionnaires:
        qn_id = doc["questionnaire_id"]
        for question in doc["questions"]:
            q_id = question["question_id"]
            answer = answers.get((qn_id, q_id))
            if answer is None or answer == "" or answer == []:
                results.append(QuestionResult(
                    qn_id, q_id, question["text"], answer, "none", STATUS_SKIPPED,
                ))
                continue
            results.append(
                _evaluate_one(knowledge, runner, evaluator_error, source,
                              qn_id, question, answer)
            )

    return Assessment(
        assessment_id=uuid.uuid4().hex[:12],
        vendor=vendor,
        mode="DEMO" if demo else "CLAUDE",
        results=results,
    )


def _evaluate_one(
    knowledge: MvpKnowledge,
    runner: Optional[SemanticEvaluationRunner],
    evaluator_error: str,
    source: str,
    qn_id: str,
    question: dict,
    answer: Any,
) -> QuestionResult:
    q_id = question["question_id"]
    text = question["text"]
    engine = knowledge.engine

    # Deterministic path (CP002).
    if question["answer_type"] in {"single_select", "multi_select"}:
        try:
            evaluation = engine.evaluate_question(qn_id, q_id, answer)
        except Exception as exc:  # noqa: BLE001
            return QuestionResult(qn_id, q_id, text, answer, "deterministic",
                                  STATUS_NEEDS_REVIEW, f"evaluation error: {exc}",
                                  needs_review=True)
        fired = [r for r in evaluation.results if r.outcome == OUTCOME_FIRED]
        findings = []
        for signal in fired:
            view = knowledge.finding_view(signal.finding_id)
            if view:
                view["condition"] = signal.condition
                findings.append(view)
        return QuestionResult(
            qn_id, q_id, text, answer, "deterministic",
            STATUS_GAP if fired else STATUS_NO_GAP,
            f"{len(evaluation.results)} gap signal(s) evaluated deterministically",
            findings=findings, source="knowledge",
        )

    # Semantic path (CP003 request -> CP004 runner -> CP003 validation).
    condition_id = _semantic_condition_id(question)
    if condition_id is None:
        return QuestionResult(
            qn_id, q_id, text, answer, "semantic", STATUS_NEEDS_REVIEW,
            "free-text answer with no semantic condition defined in knowledge; "
            "deterministic engine does not guess",
            needs_review=True,
        )
    if runner is None:
        return QuestionResult(
            qn_id, q_id, text, answer, "semantic", STATUS_NEEDS_REVIEW,
            evaluator_error or "semantic evaluation unavailable",
            needs_review=True,
        )

    try:
        result = runner.run(qn_id, q_id, str(answer))
    except SemanticError as exc:
        return QuestionResult(
            qn_id, q_id, text, answer, "semantic", STATUS_NEEDS_REVIEW,
            f"semantic evaluation rejected or unavailable: {exc}",
            needs_review=True, source=source,
        )
    except Exception as exc:  # noqa: BLE001 - one answer must not kill the run
        return QuestionResult(
            qn_id, q_id, text, answer, "semantic", STATUS_NEEDS_REVIEW,
            f"semantic evaluation failed: {type(exc).__name__}: {exc}",
            needs_review=True, source=source,
        )

    findings = []
    if result.indicates_finding:
        view = knowledge.finding_view(result.indicates_finding)
        if view:
            view["condition"] = f"semantic condition {result.condition_id}"
            findings.append(view)
    missing = ", ".join(result.missing_elements) or "none"
    return QuestionResult(
        qn_id, q_id, text, answer, "semantic",
        STATUS_GAP if findings else STATUS_NO_GAP,
        f"elements missing: {missing}",
        verdict=result.assessment,
        confidence=result.confidence,
        reason_codes=result.reason_codes,
        needs_review=True if result.needs_human_review else False,
        findings=findings, source=source,
    )
