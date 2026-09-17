#!/usr/bin/env python3
"""Ground extracted security claims against existing CC6/CC7 knowledge.

Only questions listed in QUESTION_SPECS can be touched by supplied material, and
only through attributes an extractor actually found in real document text. Every
other question stays NOT_ESTABLISHED, so material about one domain can never
establish another. Policy/procedure claims establish documented design facts
only - never operating effectiveness.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from assessment import MvpKnowledge
from claims import ClaimExtractor, DemoClaimExtractor, SecurityClaim
from ingestion import Document

ESTABLISHED = "ESTABLISHED"
PARTIAL = "PARTIALLY_ESTABLISHED"
NOT_ESTABLISHED = "NOT_ESTABLISHED"
CLARIFICATION = "CLARIFICATION_REQUIRED"

MAX_FOLLOW_UPS = 8
_PRIORITY = {CLARIFICATION: 0, PARTIAL: 1, NOT_ESTABLISHED: 2, ESTABLISHED: 9}

NO_MATERIAL = ("Not evidenced by the supplied material. This is missing material, "
               "not a control failure.")


@dataclass(frozen=True)
class Spec:
    topic: str
    design: tuple[tuple[str, str], ...]        # (attribute, human label)
    operating: tuple[tuple[str, str], ...]


QUESTION_SPECS: dict[str, Spec] = {
    "QN-ACCESS-001-Q01": Spec("mfa",
        design=(("requirement", "a second factor is required"),
                ("scope", "the systems the requirement covers")),
        operating=(("enforcement_evidence", "configuration showing the factor is enforced"),)),
    "QN-ACCESS-001-Q03": Spec("access_review",
        design=(("cadence", "the documented access review cadence"),),
        operating=(("latest_review", "the most recent completed review"),)),
    "QN-ACCESS-001-Q04": Spec("access_review",
        design=(("populations", "the identity populations in scope of the review"),),
        operating=(("latest_review", "the population covered by the most recent review"),)),
    "QN-ACCESS-001-Q05": Spec("access_review",
        design=(),
        operating=(("removal_evidence", "evidence that flagged access was removed"),)),
    "QN-ACCESS-001-Q06": Spec("termination",
        design=(("revocation_timeframe", "the committed revocation timeframe"),),
        operating=(("revocation_evidence", "evidence of an actual revocation"),)),
    "QN-ACCESS-001-Q08": Spec("privileged_access",
        design=(("privilege_restricted", "privilege is restricted to authorized personnel"),
                ("privileged_review_cadence", "the documented privileged access review cadence"),
                ("privilege_model", "standing versus time-bounded privilege")),
        operating=(("privileged_review_evidence", "a privileged access review or inventory"),)),
    "QN-ACCESS-001-Q09": Spec("encryption_at_rest",
        design=(("rest_requirement", "the documented encryption-at-rest requirement"),),
        operating=(("rest_config_evidence",
                    "storage configuration and key-custody evidence"),)),
    "QN-NETSEC-001-Q04": Spec("transport_encryption",
        design=(("transport_requirement", "the documented encrypted-transport requirement"),),
        operating=(("transport_config_evidence",
                    "deployed endpoint configuration or verification output"),)),
}


@dataclass
class Fact:
    label: str
    statement: str
    source_file: str
    source_locator: str
    snippet: str
    nature: str


@dataclass
class AreaResult:
    questionnaire_id: str
    question_id: str
    area: str
    question: str
    status: str
    reason: str
    source_file: str = ""
    source_locator: str = ""
    source_snippet: str = ""
    known_facts: list[Fact] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    evidence_needed: list[str] = field(default_factory=list)
    detail_ids: list[str] = field(default_factory=list)


@dataclass
class FollowUp:
    kind: str                 # question | evidence_request
    questionnaire_id: str
    question_id: str
    area: str
    question: str
    prompt: str
    status: str
    reason: str


@dataclass
class DocumentAssessment:
    assessment_id: str
    vendor: str
    mode: str                        # DEMO | LOCAL
    documents: list[str]
    errors: list[str]
    areas: list[AreaResult]
    claims: list[SecurityClaim] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        c = {"documents_analyzed": len(self.documents), "established": 0,
             "partially_established": 0, "missing_evidence": 0,
             "clarification_required": 0}
        for a in self.areas:
            c[{
                ESTABLISHED: "established",
                PARTIAL: "partially_established",
                NOT_ESTABLISHED: "missing_evidence",
                CLARIFICATION: "clarification_required",
            }[a.status]] += 1
        return c

    def follow_ups(self, limit: int = MAX_FOLLOW_UPS) -> list[FollowUp]:
        unresolved = [a for a in self.areas if a.status != ESTABLISHED]
        unresolved.sort(key=lambda a: (_PRIORITY[a.status], a.question_id))
        out = []
        for a in unresolved[:limit]:
            spec = QUESTION_SPECS.get(a.question_id)
            design_missing = [
                label for attr, label in (spec.design if spec else ())
                if not any(f.label == label for f in a.known_facts)
            ]
            if a.known_facts and not design_missing:
                known = "; ".join(f.statement for f in a.known_facts[:2])
                need = "; ".join(a.missing_facts) or "operating evidence for the period"
                evidence = ", ".join(a.evidence_needed)
                out.append(FollowUp(
                    "evidence_request", a.questionnaire_id, a.question_id, a.area,
                    a.question,
                    f"Your material states: {known}. Provide {need}"
                    + (f" - for example {evidence}." if evidence else "."),
                    a.status, a.reason,
                ))
            else:
                context = ""
                if a.known_facts:
                    context = (" Already established: "
                               + "; ".join(f.statement for f in a.known_facts[:2]))
                out.append(FollowUp(
                    "question", a.questionnaire_id, a.question_id, a.area,
                    a.question, a.question + context, a.status, a.reason,
                ))
        return out


class DocumentAnalyzer:
    def __init__(
        self,
        knowledge: MvpKnowledge,
        knowledge_root: Optional[Path] = None,
        extractor: Optional[ClaimExtractor] = None,
    ) -> None:
        self.knowledge = knowledge
        self.extractor = extractor or DemoClaimExtractor()
        root = Path(knowledge_root) if knowledge_root else _knowledge_root()
        self.evidence = {
            d["evidence_id"]: d
            for d in (
                json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((root / "evidence").glob("*.json"))
            )
        }

    def analyze(
        self, vendor: str, documents: list[Document], errors: list[str], demo: bool
    ) -> DocumentAssessment:
        claims = self.extractor.extract(documents)
        by_topic: dict[str, list[SecurityClaim]] = {}
        for claim in claims:
            by_topic.setdefault(claim.topic, []).append(claim)

        areas = []
        for doc in self.knowledge.questionnaires:
            qn_id = doc["questionnaire_id"]
            area = doc["name"].replace(" Readiness Questionnaire", "")
            for question in doc["questions"]:
                areas.append(self._area(qn_id, area, question, by_topic))
        return DocumentAssessment(
            assessment_id=uuid.uuid4().hex[:12],
            vendor=vendor,
            mode="DEMO" if demo else "LOCAL",
            documents=[d.filename for d in documents],
            errors=list(errors),
            areas=areas,
            claims=claims,
        )

    def _area(
        self, qn_id: str, area: str, question: dict,
        by_topic: dict[str, list[SecurityClaim]],
    ) -> AreaResult:
        expected = [e for e in question.get("expected_evidence", []) if e in self.evidence]
        base = dict(
            questionnaire_id=qn_id, question_id=question["question_id"], area=area,
            question=question["text"],
            evidence_needed=[self.evidence[e]["name"] for e in expected],
            detail_ids=expected + question.get("related_controls", []),
        )
        spec = QUESTION_SPECS.get(question["question_id"])
        claims = by_topic.get(spec.topic, []) if spec else []
        if not spec or not claims:
            return AreaResult(status=NOT_ESTABLISHED, reason=NO_MATERIAL, **base)

        known: list[Fact] = []
        missing: list[str] = []
        design_known = operating_known = 0
        for group, is_design in ((spec.design, True), (spec.operating, False)):
            for attr, label in group:
                # Operating attributes are only ever set by an extractor on
                # operating-nature text, so attribute presence is sufficient here.
                supporting = next((c for c in claims if attr in c.attributes), None)
                if supporting is None:
                    missing.append(label)
                    continue
                value = supporting.attributes[attr]
                shown = ", ".join(value) if isinstance(value, list) else str(value)
                known.append(Fact(
                    label=label,
                    statement=f"{label}: {shown}",
                    source_file=supporting.source_filename,
                    source_locator=supporting.source_locator,
                    snippet=supporting.snippet,
                    nature=supporting.evidence_nature,
                ))
                if is_design:
                    design_known += 1
                else:
                    operating_known += 1

        if not known:
            return AreaResult(
                status=CLARIFICATION,
                reason="Supplied material mentions this area but does not state what "
                       "this question asks. Confirm it directly.",
                missing_facts=missing, **base,
            )

        all_design = design_known == len(spec.design)
        all_operating = operating_known == len(spec.operating)
        if all_design and all_operating:
            status = ESTABLISHED
            reason = "Established by the supplied material, including operating evidence."
        else:
            status = PARTIAL
            reason = (
                "Documented design facts are established by the supplied material, but "
                "operating evidence for the period was not provided; a documented "
                "requirement is not evidence of operating effectiveness."
                if operating_known == 0 else
                "Partly established by the supplied material; operating evidence is "
                "still incomplete."
            )

        first = known[0]
        return AreaResult(
            status=status, reason=reason, known_facts=known, missing_facts=missing,
            source_file=first.source_file, source_locator=first.source_locator,
            source_snippet=first.snippet, **base,
        )


def _knowledge_root() -> Path:
    from evaluation.engine import resolve_knowledge_root

    return resolve_knowledge_root()
