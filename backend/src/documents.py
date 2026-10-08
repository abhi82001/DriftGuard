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
from evidence.authority import (ATTESTATION, ESTABLISHING, PERIOD_BLOCKING, PERIOD_COVERS, PERIOD_STALE, PERIOD_UNKNOWN,
                                DocumentAuthority, can_establish, classify_document)
from evidence.specificity import CATEGORICAL_ATTRS, is_specific, normalize_value
from evidence.authority import PERIOD_ENDED, FRESHNESS_DAYS, _dates, _iso
from dataclasses import replace as _replace
from datetime import timedelta
import re

_BRIDGE = "BRIDGE_LETTER"
_HEAD_CHARS = 2500   # "first pages" of extracted text


@dataclass(frozen=True)
class ReviewedAuthority(DocumentAuthority):
    """DocumentAuthority plus content-based review flag and bridge-letter coverage."""
    review_flag: str = ""        # filename/content mismatch, for human review
    bridge_through: str = ""     # ISO date a matching bridge letter extends coverage to
    bridge_file: str = ""
    period_check: str = ""       # how the period state was reached, incl. bridge decisions

    def period_state(self, as_of: date) -> str:
        state = super().period_state(as_of)
        through = _iso(self.bridge_through)
        if state in (PERIOD_ENDED, PERIOD_STALE) and through and as_of <= through + timedelta(days=FRESHNESS_DAYS):
            return PERIOD_COVERS
        return state


def _content_signal(text: str) -> Optional[tuple[str, str]]:
    """(synthetic title, label) from headings in the first pages, or None."""
    head = " ".join(text[:_HEAD_CHARS].lower().split())
    if "bridge letter" in head or "gap letter" in head:
        return "bridge letter", "bridge letter"
    m = re.search(r"\bsoc\s*([12])\b", head)
    if m and ("independent service auditor" in head or re.search(r"\btype\s*(2|ii|1|i)\b", head)
              or "system and organization controls" in head):
        t = re.search(r"\btype\s*(2|ii|1|i)\b", head)
        kind = "" if not t else (" type 2" if t.group(1) in ("2", "ii") else " type 1")
        return f"soc {m.group(1)}{kind} report", f"SOC {m.group(1)} report"
    if "independent service auditor" in head:
        return "soc 2 report", "Independent Service Auditor's report"
    if "privacy impact assessment" in head:
        return "privacy impact assessment", "Privacy Impact Assessment"
    return None


def resolve_authority(filename: str, text: str) -> ReviewedAuthority:
    """Filename-based classification, overridden by a content heading; mismatches are flagged."""
    base = classify_document(filename, text[:6000])
    signal = _content_signal(text)
    if signal is None:
        return ReviewedAuthority(**{f: getattr(base, f) for f in DocumentAuthority.__dataclass_fields__})
    content = classify_document(signal[0] + ".txt", text[:6000])
    rtype = content.report_type
    # A content type of 'unspecified' must not downgrade a filename that stated the type.
    if rtype.endswith("TYPE_UNSPECIFIED") and base.report_type.startswith(rtype.split("_TYPE")[0]):
        rtype = base.report_type
    flag = ""
    if (content.authority, rtype) != (base.authority, base.report_type):
        flag = (f"filename suggests {base.authority}/{base.report_type or '-'} but document content "
                f"('{signal[1]}' heading) indicates {content.authority}/{rtype or '-'}; "
                "content signal applied, review recommended")
    return ReviewedAuthority(
        filename, content.authority, rtype, base.scope, base.third_party,
        content.period_start or base.period_start, content.period_end or base.period_end,
        review_flag=flag)


def apply_bridge_letters(auths: dict[str, ReviewedAuthority], documents: list) -> dict[str, ReviewedAuthority]:
    """Extend an attestation's coverage past its audit period only for a bridge letter that
    names the same scope and the same report period end. Decision is recorded in period_check."""
    text_of = {d.filename: d.text for d in documents}
    out = dict(auths)
    bridges = [a for a in auths.values() if a.report_type == _BRIDGE]
    for name, a in auths.items():
        if a.authority != ATTESTATION or a.report_type in ("", _BRIDGE) or not a.period_end:
            continue
        notes, best = [], None
        for b in bridges:
            dates = sorted(set(_dates(text_of.get(b.filename, "")[:_HEAD_CHARS]) + ([b.period_end] if b.period_end else [])))
            if not a.scope or b.scope != a.scope:
                notes.append(f"bridge letter {b.filename} not applied: scope "
                             f"'{b.scope or 'unstated'}' does not match report scope '{a.scope or 'unstated'}'")
            elif a.period_end not in dates:
                notes.append(f"bridge letter {b.filename} not applied: it does not cite the report's audit period end {a.period_end}")
            elif dates[-1] <= a.period_end:
                notes.append(f"bridge letter {b.filename} not applied: it states no date after {a.period_end}")
            else:
                best = max(best or dates[-1], dates[-1])
                notes.append(f"bridge letter {b.filename} extends coverage from {a.period_end} through {dates[-1]} "
                             "(scope and report period match); the gap is covered by management assertion, not audited")
                bridge_file = b.filename
        fields = {"period_check": "; ".join(notes)} if notes else {}
        if best:
            fields.update(bridge_through=best, bridge_file=bridge_file)
        if fields:
            out[name] = _replace(a, **fields)
    return out

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
    # CP019: authority/scope/period tags so facts from different scopes never merge.
    authority: str = "UNCLASSIFIED"
    scope: str = ""
    report_type: str = ""
    audit_period: str = ""
    # CP019: model-interpreted facts are marked and carry source ids; they never
    # establish a requirement on their own (see DocumentAnalyzer._evaluate).
    ai_derived: bool = False
    source_ids: tuple = ()


AI_EXTRACTION_PREFIXES = ("semantic",)


def is_ai_derived(claim) -> bool:
    return str(getattr(claim, "extraction_method", "")).startswith(AI_EXTRACTION_PREFIXES)


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
    # Separate per-scope observations, context-only material and rejected sources.
    scoped_observations: list[dict] = field(default_factory=list)
    context_sources: list[dict] = field(default_factory=list)
    rejected_sources: list[dict] = field(default_factory=list)
    conflict_details: list[dict] = field(default_factory=list)


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
    extraction: list[dict] = field(default_factory=list)   # per-file typed extraction status
    run_stamp: dict = field(default_factory=dict)          # input hash, assessment date, versions

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

        authorities = apply_bridge_letters(
            {d.filename: resolve_authority(d.filename, d.text) for d in documents}, documents)
        areas = []
        for doc in self.knowledge.questionnaires:
            qn_id = doc["questionnaire_id"]
            area = doc["name"].replace(" Readiness Questionnaire", "")
            for question in doc["questions"]:
                areas.append(self._area(qn_id, area, question, by_topic, authorities, assessment_date))
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
        authorities: Optional[dict] = None, as_of: Optional[date] = None,
    ) -> AreaResult:
        authorities = authorities or {}
        as_of = as_of or date.today()
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

        # CP019: authority, third-party scope and audit-period gates. Context-only
        # and rejected sources are carried for explanation, never as support.
        groups: dict[str, list[SecurityClaim]] = {}
        group_auth: dict[str, DocumentAuthority] = {}
        context: dict[str, dict] = {}
        rejected: dict[str, dict] = {}
        for c in claims:
            auth = authorities.get(c.source_filename) or DocumentAuthority(c.source_filename)
            ok, why = can_establish(auth)
            if not ok:
                bucket = context if auth.authority not in ESTABLISHING else rejected
                bucket.setdefault(c.source_filename, dict(auth.tag(as_of), reason=why))
                continue
            state = auth.period_state(as_of) if auth.authority == ATTESTATION else PERIOD_COVERS
            if state in PERIOD_BLOCKING:
                rejected.setdefault(c.source_filename, dict(auth.tag(as_of),
                    reason=("audit period ends more than 12 months before the assessment date" if state == PERIOD_STALE
                            else "audit period starts after the assessment date")))
                continue
            if auth.design_only and c.evidence_nature in spec.operating_roles:
                rejected.setdefault(c.source_filename, dict(auth.tag(as_of),
                    reason="a Type 1 report describes design at a point in time, not operating effectiveness"))
                continue
            groups.setdefault(auth.scope_key, []).append(c)
            group_auth[auth.scope_key] = auth
        extra = dict(context_sources=sorted(context.values(), key=lambda x: x["filename"]),
                     rejected_sources=sorted(rejected.values(), key=lambda x: x["filename"]))

        if not groups:
            return AreaResult(
                status=NOT_ESTABLISHED,
                reason=("The only material on this topic comes from sources that cannot establish a control "
                        "(context-only, out-of-scope or outside the audit-period window). "
                        + NO_MATERIAL), **extra, **base)

        results = {k: self._evaluate(spec, g, group_auth[k], as_of) for k, g in sorted(groups.items())}
        observations = [dict(scope=group_auth[k].scope or "UNSCOPED", report_type=group_auth[k].report_type,
                             period=(f"{group_auth[k].period_start} to {group_auth[k].period_end}"
                                     if group_auth[k].period_end else ""),
                             status=r["status"],
                             period_check=getattr(group_auth[k], "period_check", ""),
                             review_flag=getattr(group_auth[k], "review_flag", ""),
                             facts=[dict(statement=f.statement, filename=f.source_file, locator=f.source_locator)
                                    for f in r["known"]],
                             missing=r["missing"])
                        for k, r in results.items()]
        scoped = observations if len(results) > 1 else []
        conflicted = [k for k, r in results.items() if r["conflicts"]]
        if conflicted:
            r = results[conflicted[0]]
            first = r["known"][0]
            details = [d for k in conflicted for d in results[k]["conflicts"]]
            d0 = details[0]
            return AreaResult(
                status=CONFLICT,
                reason=(f"Within scope {d0['scope'] or 'UNSCOPED'}, '{d0['attribute']}' differs between two facts: "
                        f"{d0['value_a']!r} ({d0['file_a']}, {d0['locator_a']}) vs {d0['value_b']!r} "
                        f"({d0['file_b']}, {d0['locator_b']}). DriftGuard did not choose one silently."),
                known_facts=r["known"],
                missing_facts=r["missing"] + [f"resolve conflict: {x}" for x in r["conflict_labels"]],
                source_file=first.source_file, source_locator=first.source_locator,
                source_snippet=first.snippet, scoped_observations=scoped, conflict_details=details,
                **extra, **base)

        rank = {ESTABLISHED: 0, PARTIAL: 1, CLARIFICATION: 2}
        best = sorted(results, key=lambda k: (rank.get(results[k]["status"], 3), k))[0]
        r = results[best]
        reason = r["reason"]
        if len(results) > 1:
            reason = (f"Best-supported scope {group_auth[best].scope or 'UNSCOPED'}: {reason} "
                      "Other scopes are reported separately and are not combined.")
        if not r["known"]:
            return AreaResult(status=r["status"], reason=reason, missing_facts=r["missing"],
                              scoped_observations=scoped, **extra, **base)
        first = r["known"][0]
        return AreaResult(
            status=r["status"], reason=reason, known_facts=r["known"], missing_facts=r["missing"],
            source_file=first.source_file, source_locator=first.source_locator,
            source_snippet=first.snippet, scoped_observations=scoped, **extra, **base,
        )

    def _evaluate(self, spec, claims, auth: DocumentAuthority, as_of: date) -> dict:
        """Evaluate one scope group's claims against the contract (never mixes scopes)."""
        known: list[Fact] = []
        missing: list[str] = []
        conflicts: list[dict] = []
        conflict_labels: list[str] = []
        ai_only: list[str] = []
        ai_disagrees: list[str] = []
        design_known = operating_known = 0
        tag = dict(authority=auth.authority, scope=auth.scope, report_type=auth.report_type,
                   audit_period=(f"{auth.period_start} to {auth.period_end}" if auth.period_end else ""))
        for group, is_design in ((spec.design, True), (spec.operating, False)):
            eligible_roles = spec.design_roles if is_design else spec.operating_roles
            for attr, label in group:
                candidates = [c for c in claims if attr in c.attributes and c.evidence_nature in eligible_roles]
                supporting = []
                future_dated = []
                generic_only = []
                for c in candidates:
                    raw_date = getattr(c, "evidence_date", "")
                    try:
                        is_future = bool(raw_date) and date.fromisoformat(raw_date) > date.today()
                    except ValueError:
                        is_future = True
                    if is_future:
                        future_dated.append(c)
                    elif not is_specific(c, attr, spec.topic):
                        generic_only.append(c)
                    else:
                        supporting.append(c)
                if not supporting:
                    missing.append(label + (
                        " (future/invalid evidence date requires clarification)" if future_dated else
                        " (only a generic value without question-specific context was found)" if generic_only else ""))
                    continue
                # Only genuinely contradictory categorical values within one scope
                # conflict; differing matched wording of a requirement does not.
                det = [c for c in supporting if not is_ai_derived(c)]
                ai = [c for c in supporting if is_ai_derived(c)]
                if ai:
                    det_values = {normalize_value(c.attributes[attr]) for c in det}
                    if not det:
                        ai_only.append(label)
                    elif any(normalize_value(c.attributes[attr]) not in det_values for c in ai):
                        ai_disagrees.append(label)
                if attr in CATEGORICAL_ATTRS:
                    seen: dict = {}
                    for c in det:                       # a model can never create a conflict
                        seen.setdefault(normalize_value(c.attributes[attr]), c)
                    if len(seen) > 1:
                        ca, cb = list(seen.values())[:2]
                        conflict_labels.append(label)
                        conflicts.append(dict(
                            scope=auth.scope, report_type=auth.report_type, attribute=attr,
                            value_a=ca.attributes[attr], file_a=ca.source_filename, locator_a=ca.source_locator,
                            value_b=cb.attributes[attr], file_b=cb.source_filename, locator_b=cb.source_locator))
                for c in supporting:
                    value = c.attributes[attr]
                    shown = ", ".join(value) if isinstance(value, list) else str(value)
                    known.append(Fact(
                        label=label, statement=f"{label}: {shown}",
                        source_file=c.source_filename, source_locator=c.source_locator,
                        snippet=c.snippet, nature=c.evidence_nature,
                        extraction_method=getattr(c, "extraction_method", "unknown"),
                        artifact_type=getattr(c, "artifact_type", c.evidence_nature),
                        source_role=c.evidence_nature, ai_derived=is_ai_derived(c),
                        source_ids=(f"{c.source_filename}#{c.source_locator}",), **tag,
                    ))
                if is_design:
                    design_known += 1
                else:
                    operating_known += 1

        out = dict(known=known, missing=missing, conflicts=conflicts, conflict_labels=conflict_labels)
        if conflicts:
            return dict(out, status=CONFLICT, reason="conflict")
        if not known:
            return dict(out, status=CLARIFICATION, reason=(
                "Supplied material mentions this area but eligible evidence does not state what this question asks. Confirm it directly."))
        all_design = design_known == len(spec.design)
        all_operating = operating_known == len(spec.operating)
        for label in ai_only:
            missing.append(f"human confirmation of a model-interpreted fact: {label}")
        for label in ai_disagrees:
            missing.append(f"human confirmation: a model-interpreted value for '{label}' differs from the deterministic value")
        if (ai_only or ai_disagrees) and all_design and all_operating:
            return dict(out, status=PARTIAL, reason=(
                "Contract facts are present, but at least one rests on model interpretation alone or disagrees "
                "with the deterministic reading; model output cannot establish a requirement without confirmation."))
        period_unknown = auth.authority == ATTESTATION and auth.period_state(as_of) == PERIOD_UNKNOWN
        if all_design and all_operating and not period_unknown:
            return dict(out, status=ESTABLISHED,
                        reason="Established by eligible supplied material for this evidence contract; this is not a compliance conclusion.")
        if all_design and all_operating:
            missing.append("audit period of the attestation (not stated; period is NOT_EVALUATED)")
            return dict(out, status=PARTIAL, reason=(
                "Contract facts are present, but the attestation's audit period is unknown, so period validity is NOT_EVALUATED."))
        return dict(out, status=PARTIAL, reason=(
            "Documented design facts are established by eligible supplied material, but operating evidence for the period was not provided; a documented requirement is not evidence of operating effectiveness."
            if operating_known == 0 and spec.operating else
            "Partly established by eligible supplied material; material contract facts remain unresolved."))


def _knowledge_root() -> Path:
    from evaluation.engine import resolve_knowledge_root

    return resolve_knowledge_root()
