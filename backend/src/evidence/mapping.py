#!/usr/bin/env python3
"""CP009: conservative evidence-to-question/control lineage, not a compliance evaluator.

The questionnaire is the mapping authority. Only an exact classified evidence ID
may satisfy an expected-evidence *type* match; text claims are contextual
observations and cannot silently become EV-IAM-001 or prove enforcement.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .backbone import EvidenceAnalysis, ArtifactProvenance
from .knowledge import _knowledge_root

OBSERVED = "EVIDENCE_OBSERVED"
PARTIAL = "PARTIAL_EVIDENCE"
REQUEST = "EVIDENCE_REQUEST"
REVIEW = "HUMAN_REVIEW"
NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True)
class EvidenceLink:
    artifact_id: str
    filename: str
    fact_keys: tuple[str, ...]
    provenance: tuple[ArtifactProvenance, ...]

    def to_dict(self) -> dict:
        return dict(artifact_id=self.artifact_id, filename=self.filename,
                    fact_keys=list(self.fact_keys),
                    provenance=[p.to_dict() for p in self.provenance])


@dataclass(frozen=True)
class QuestionEvidence:
    question_id: str
    question: str
    related_controls: tuple[str, ...]
    expected_evidence: tuple[str, ...]
    state: str
    explanation: str
    next_action: str
    links: tuple[EvidenceLink, ...]

    def to_dict(self) -> dict:
        return dict(question_id=self.question_id, question=self.question,
                    related_controls=list(self.related_controls),
                    expected_evidence=list(self.expected_evidence), state=self.state,
                    explanation=self.explanation, next_action=self.next_action,
                    links=[link.to_dict() for link in self.links])


@dataclass(frozen=True)
class MappingView:
    questionnaire_id: str
    questions: tuple[QuestionEvidence, ...]

    def to_dict(self) -> dict:
        return dict(record_type="evidence_question_mapping",
                    questionnaire_id=self.questionnaire_id,
                    questions=[q.to_dict() for q in self.questions])


def map_questionnaire(analysis: EvidenceAnalysis,
                      questionnaire_id: str = "QN-ACCESS-001",
                      knowledge_root: Optional[Path] = None) -> MappingView:
    """Map existing classified artifacts to authoritative questionnaire edges.

    CP009 slice evaluates Q01 and Q03-Q06 only. Q02 needs explicit auth-path
    enumeration, not a keyword match. Other questions remain NOT_EVALUATED.
    """
    if questionnaire_id != "QN-ACCESS-001":
        raise ValueError("CP009 slice currently supports QN-ACCESS-001 only")
    base = Path(knowledge_root) if knowledge_root is not None else _knowledge_root()
    questionnaire = json.loads((base / "questionnaires" /
                                f"{questionnaire_id}.json").read_text(encoding="utf-8"))
    output = []
    for question in questionnaire["questions"]:
        qid = question["question_id"]
        expected = tuple(question.get("expected_evidence", ()))
        controls = tuple(question.get("related_controls", ()))
        for evidence_id in expected:
            if not (base / "evidence" / f"{evidence_id}.json").is_file():
                raise ValueError(f"Question {qid} references missing evidence {evidence_id}")
        for control_id in controls:
            if not (base / "controls" / f"{control_id}.json").is_file():
                raise ValueError(f"Question {qid} references missing control {control_id}")
        if qid not in {f"QN-ACCESS-001-Q{i:02d}" for i in (1, 3, 4, 5, 6)}:
            output.append(QuestionEvidence(qid, question["text"], controls, expected,
                NOT_EVALUATED, "Outside CP009 deterministic vertical slice.",
                "Use human assessment; do not infer an answer from uploaded files.", ()))
            continue

        # Strict ID matching prevents a policy paragraph from impersonating an
        # identity-provider configuration export or a user-access-review record.
        matches = [a for a in analysis.artifacts if a.knowledge_evidence_id in expected]
        links = tuple(EvidenceLink(a.artifact_id, a.filename,
            tuple(f.key for f in a.facts),
            tuple(dict.fromkeys(p for f in a.facts for p in f.provenance)))
            for a in matches)
        if not matches:
            context = [a for a in analysis.artifacts
                       if qid == "QN-ACCESS-001-Q01" and
                       any(f.key.startswith("mfa.") for f in a.facts)]
            context_links = tuple(EvidenceLink(a.artifact_id, a.filename,
                tuple(f.key for f in a.facts if f.key.startswith("mfa.")),
                tuple(dict.fromkeys(p for f in a.facts if f.key.startswith("mfa.")
                                    for p in f.provenance))) for a in context)
            explanation = ("MFA-related text was observed, but it is not a classified "
                           "identity-provider enforcement export." if context else
                           "No artifact with the expected evidence ID was classified.")
            action = ("Obtain an identity-provider MFA/conditional-access export "
                      "with enforcement scope, exclusions and applicable period." if
                      qid == "QN-ACCESS-001-Q01" else
                      f"Upload and classify the required evidence: {', '.join(expected)}.")
            output.append(QuestionEvidence(qid, question["text"], controls, expected,
                                           REQUEST, explanation, action, context_links))
            continue
        if len(matches) > 1 or any(a.needs_review for a in matches):
            state = REVIEW
            detail = "Matching evidence is present; one or more artifacts require human review."
        elif any(c.state != "SUPPORTED" for a in matches for c in a.checks):
            state = PARTIAL
            detail = "Matching evidence is present, but its artifact-level checks are incomplete."
        else:
            state = OBSERVED
            detail = "Expected evidence type was observed; question answer and control outcome are not established."
        # Never let one UAR sheet prove review frequency or complete population.
        if qid in ("QN-ACCESS-001-Q03", "QN-ACCESS-001-Q04", "QN-ACCESS-001-Q06") and state == OBSERVED:
            state = PARTIAL
            detail = "A matching review record exists; one artifact cannot establish full cadence or scope."
        action = ("Review flagged source rows and obtain independent population, period, "
                  "and closure evidence as applicable." if state != OBSERVED else
                  "Verify scope, period and enforcement independently before answering the question.")
        output.append(QuestionEvidence(qid, question["text"], controls, expected,
                                       state, detail, action, links))
    return MappingView(questionnaire_id, tuple(output))
