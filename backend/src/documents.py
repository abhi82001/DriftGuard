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
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from assessment import MvpKnowledge
from claims import ClaimExtractor, DemoClaimExtractor, SecurityClaim
from narrative_claims import CompositeGroundedExtractor, HybridGroundedExtractor
from evidence import StructuredEvidenceResult
from ingestion import Document
from bcp_dr import RecoveryAssessment, extract_recovery_facts, reconcile_recovery
from evidence.graph import EvidenceGraph

ESTABLISHED = "ESTABLISHED"
PARTIAL = "PARTIALLY_ESTABLISHED"
NOT_ESTABLISHED = "NOT_ESTABLISHED"
CLARIFICATION = "CLARIFICATION_REQUIRED"
CONFLICT = "CONFLICT"
NOT_EVALUATED = "NOT_EVALUATED"

MAX_FOLLOW_UPS = 8
_PRIORITY = {CONFLICT: 0, CLARIFICATION: 1, PARTIAL: 2, NOT_ESTABLISHED: 3, NOT_EVALUATED: 4, ESTABLISHED: 9}

NO_MATERIAL = ("Not evidenced by the supplied material. This is missing material, "
               "not a control failure.")


from questionnaire_contracts import Spec, QUESTION_SPECS


@dataclass
class Fact:
    label: str
    statement: str
    source_file: str
    source_locator: str
    snippet: str
    nature: str
    extraction_method: str = "unknown"
    artifact_type: str = "UNKNOWN"
    source_role: str = "UNKNOWN"


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
    # CP007: structured evidence read from tabular uploads, before assessment.
    evidence: list[StructuredEvidenceResult] = field(default_factory=list)
    recovery: Optional[RecoveryAssessment] = None
    semantic_status: str = "NEEDS_REVIEW"
    semantic_rejections: int = 0
    semantic_conflicts: list[dict] = field(default_factory=list)
    evidence_graph: Optional[EvidenceGraph] = None
    files_received: int = 0

    @property
    def counts(self) -> dict:
        c = {"documents_analyzed": len(self.documents), "established": 0,
             "partially_established": 0, "missing_evidence": 0,
             "clarification_required": 0, "conflict": 0, "not_evaluated": 0}
        for a in self.areas:
            c[{
                ESTABLISHED: "established",
                PARTIAL: "partially_established",
                NOT_ESTABLISHED: "missing_evidence",
                CLARIFICATION: "clarification_required",
                CONFLICT: "conflict",
                NOT_EVALUATED: "not_evaluated",
            }[a.status]] += 1
        return c

    @property
    def contract_coverage(self) -> dict:
        return {"executable_contracts": sum(a.question_id in QUESTION_SPECS for a in self.areas),
                "requirements_total": len(self.areas),
                "requirements_without_contract": sum(a.question_id not in QUESTION_SPECS for a in self.areas)}

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


from policy_conflicts import detect_polarity_conflicts


class DocumentAnalyzer:
    def __init__(
        self,
        knowledge: MvpKnowledge,
        knowledge_root: Optional[Path] = None,
        extractor: Optional[ClaimExtractor] = None,
    ) -> None:
        self.knowledge = knowledge
        self.extractor = extractor or HybridGroundedExtractor()
        root = Path(knowledge_root) if knowledge_root else _knowledge_root()
        self.evidence = {
            d["evidence_id"]: d
            for d in (
                json.loads(p.read_text(encoding="utf-8"))
                for p in sorted((root / "evidence").glob("*.json"))
            )
        }

    def analyze(
        self, vendor: str, documents: list[Document], errors: list[str], demo: bool,
        evidence: Optional[list[StructuredEvidenceResult]] = None,
        assessment_date: Optional[date] = None,
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
        self._apply_temporal_rules(areas, as_of=assessment_date)
        return DocumentAssessment(
            assessment_id=uuid.uuid4().hex,
            vendor=vendor,
            mode="DEMO" if demo else "LOCAL",
            documents=[d.filename for d in documents],
            errors=list(errors),
            areas=areas,
            claims=claims,
            evidence=list(evidence or []),
            recovery=reconcile_recovery(extract_recovery_facts(documents), as_of=assessment_date),
            semantic_status=getattr(self.extractor, "semantic_status", "NEEDS_REVIEW"),
            semantic_rejections=len(getattr(self.extractor, "semantic_rejections", [])),
            semantic_conflicts=list(getattr(self.extractor, "semantic_conflicts", []))
            + detect_polarity_conflicts(documents),
        )


    def _apply_temporal_rules(self, areas, *, as_of=None):
        """CP016 shared freshness rule for cadence-governed operating evidence."""
        from evidence.temporal_review import assess_freshness
        as_of = as_of or date.today()
        for a in areas:
            if a.question_id != "QN-ACCESS-001-Q03":
                continue
            cadence=None; review=None
            for f in a.known_facts:
                low=f.statement.lower()
                if 'cadence' in low:
                    for c in ('daily','weekly','monthly','quarterly','semiannual','annually','annual'):
                        if c in low: cadence='annual' if c=='annually' else c
                if 'most recent completed review' in low:
                    import re
                    m=re.search(r'20\d{2}-\d{2}-\d{2}',f.statement)
                    if m: review=m.group(0)
            if cadence and review:
                fresh=assess_freshness(review,cadence,as_of=as_of)
                if fresh['state']=='STALE':
                    a.status=PARTIAL
                    a.reason=fresh['reason'] + '; stale operating evidence does not establish current operation.'
                    a.missing_facts.append('current access review evidence')
                elif fresh['state']=='REJECTED':
                    a.status=PARTIAL
                    a.reason='Future-dated operating evidence was rejected; current operating evidence is still required.'

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
        if spec is None:
            return AreaResult(status=NOT_EVALUATED,
                reason="Evaluation could not execute because no runtime contract was available. This is an engine limitation, not a vendor finding.", **base)
        if not claims:
            return AreaResult(status=NOT_ESTABLISHED, reason=NO_MATERIAL, **base)

        known: list[Fact] = []
        missing: list[str] = []
        conflicts: list[str] = []
        design_known = operating_known = 0
        for group, is_design in ((spec.design, True), (spec.operating, False)):
            eligible_roles = spec.design_roles if is_design else spec.operating_roles
            for attr, label in group:
                candidates = [c for c in claims if attr in c.attributes and c.evidence_nature in eligible_roles]
                supporting = []
                future_dated = []
                for c in candidates:
                    raw_date = getattr(c, "evidence_date", "")
                    try:
                        is_future = bool(raw_date) and date.fromisoformat(raw_date) > date.today()
                    except ValueError:
                        is_future = True
                    (future_dated if is_future else supporting).append(c)
                if not supporting:
                    missing.append(label + (" (future/invalid evidence date requires clarification)" if future_dated else ""))
                    continue
                # Materially different normalized values from eligible sources are
                # not silently resolved by source order.
                values = {repr(c.attributes[attr]) for c in supporting}
                if len(values) > 1:
                    conflicts.append(label)
                for c in supporting:
                    value = c.attributes[attr]
                    shown = ", ".join(value) if isinstance(value, list) else str(value)
                    known.append(Fact(
                        label=label, statement=f"{label}: {shown}",
                        source_file=c.source_filename, source_locator=c.source_locator,
                        snippet=c.snippet, nature=c.evidence_nature,
                        extraction_method=getattr(c, "extraction_method", "unknown"),
                        artifact_type=getattr(c, "artifact_type", c.evidence_nature),
                        source_role=c.evidence_nature,
                    ))
                if is_design:
                    design_known += 1
                else:
                    operating_known += 1

        if conflicts:
            first = known[0]
            return AreaResult(
                status=CONFLICT,
                reason="Eligible evidence sources materially disagree; DriftGuard did not choose one source silently.",
                known_facts=known, missing_facts=missing + [f"resolve conflict: {x}" for x in conflicts],
                source_file=first.source_file, source_locator=first.source_locator,
                source_snippet=first.snippet, **base,
            )

        if not known:
            return AreaResult(
                status=CLARIFICATION if claims else NOT_ESTABLISHED,
                reason=("Supplied material mentions this area but eligible evidence does not state what this question asks. Confirm it directly."
                        if claims else NO_MATERIAL),
                missing_facts=missing, **base,
            )

        all_design = design_known == len(spec.design)
        all_operating = operating_known == len(spec.operating)
        if all_design and all_operating:
            status = ESTABLISHED
            reason = "Established by eligible supplied material for this evidence contract; this is not a compliance conclusion."
        else:
            status = PARTIAL
            reason = (
                "Documented design facts are established by eligible supplied material, but operating evidence for the period was not provided; a documented requirement is not evidence of operating effectiveness."
                if operating_known == 0 and spec.operating else
                "Partly established by eligible supplied material; material contract facts remain unresolved."
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
