#!/usr/bin/env python3
"""Evidence QA exception report (CP007 Phase 1, presentation layer).

Turns an existing StructuredEvidenceResult into the page a compliance lead
reads before evidence goes to their auditor. This module performs no analysis:
it re-orders and re-words what the validation layer already decided.

Two rules hold everywhere:

  * a headline is built only from the values already on the check (or on the
    conflicting facts the check names). If those cannot produce a clean
    sentence, the check's own detail is used verbatim. Nothing is guessed, and
    no remediation advice is invented.
  * exact provenance is carried through untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .model import (
    CONFLICT,
    MISSING,
    NEEDS_REVIEW,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    EvidenceFact,
    Provenance,
    StructuredEvidenceResult,
    ValidationCheck,
)
from .validation import (
    CHECK_CONSISTENCY,
    CHECK_DECISIONS,
    CHECK_EXCEPTIONS,
    CHECK_IDENTITY,
    CHECK_PERIOD,
    CHECK_POPULATION,
    CHECK_POST_CHANGE,
    CHECK_REMEDIATION,
    EXPECTED_IDENTITY_TYPES,
)

# Most serious first. Everything in this tuple is an exception to look at.
EXCEPTION_ORDER = (CONFLICT, NEEDS_REVIEW, PARTIALLY_SUPPORTED, MISSING)
_RANK = {state: index for index, state in enumerate(EXCEPTION_ORDER)}

# Within one state, show what a compliance lead is asked about first.
_CHECK_PRIORITY = (CHECK_CONSISTENCY, CHECK_POPULATION, CHECK_DECISIONS,
                   CHECK_REMEDIATION, CHECK_POST_CHANGE, CHECK_IDENTITY,
                   CHECK_PERIOD, CHECK_EXCEPTIONS)

STATE_WORDS = {
    CONFLICT: "Numbers disagree",
    NEEDS_REVIEW: "Needs a human",
    PARTIALLY_SUPPORTED: "Partly evidenced",
    MISSING: "Not in this artifact",
    SUPPORTED: "Reconciled",
}

NO_EXCEPTIONS = (
    "Nothing in this artifact needs attention before it is sent: every check "
    "reconciled against the artifact's own numbers."
)


@dataclass(frozen=True)
class ReportLine:
    """One validation check, phrased for someone who did not build DriftGuard."""

    check_id: str
    name: str
    state: str
    headline: str
    detail: str
    grounding: str
    provenance: tuple[Provenance, ...] = ()

    @property
    def state_word(self) -> str:
        return STATE_WORDS.get(self.state, self.state.replace("_", " "))


@dataclass(frozen=True)
class EvidenceReport:
    filename: str
    evidence_type: str
    state: str
    review_period: str
    campaign_status: str
    exceptions: tuple[ReportLine, ...]
    reconciled: tuple[ReportLine, ...]
    facts: tuple[EvidenceFact, ...]
    notes: tuple[str, ...]
    knowledge_evidence_id: str = ""
    extractor: str = ""

    @property
    def exception_count(self) -> int:
        return len(self.exceptions)


def build_report(result: StructuredEvidenceResult) -> EvidenceReport:
    lines = [_line(result, check) for check in result.checks]
    exceptions = sorted(
        (line for line in lines if line.state in _RANK),
        key=lambda line: (_RANK[line.state], _priority(line.check_id)),
    )
    return EvidenceReport(
        filename=result.filename,
        evidence_type=result.evidence_type,
        state=result.state,
        review_period=_period(result),
        campaign_status=str(result.value("campaign_status") or ""),
        exceptions=tuple(exceptions),
        reconciled=tuple(line for line in lines if line.state == SUPPORTED),
        facts=result.facts,
        notes=result.notes,
        knowledge_evidence_id=result.knowledge_evidence_id,
        extractor=result.extractor,
    )


def _priority(check_id: str) -> tuple[int, str]:
    order = (_CHECK_PRIORITY.index(check_id) if check_id in _CHECK_PRIORITY
             else len(_CHECK_PRIORITY))
    return order, check_id


def _period(result: StructuredEvidenceResult) -> str:
    start = result.value("review_period_start")
    end = result.value("review_period_end")
    if start and end:
        return f"{start} to {end}"
    return str(start or end or result.value("review_completed_date") or "")


def _line(result: StructuredEvidenceResult, check: ValidationCheck) -> ReportLine:
    headline = _headline(result, check) or check.detail
    return ReportLine(
        check_id=check.check_id, name=check.name, state=check.state,
        headline=headline, detail=check.detail, grounding=check.grounding,
        provenance=check.provenance,
    )


# ---------------------------------------------------------------- headlines
def _headline(result: StructuredEvidenceResult, check: ValidationCheck) -> Optional[str]:
    """A plain sentence, or None to fall back to the check's own detail."""
    builder = _BUILDERS.get(check.check_id)
    if builder is None:
        return None
    try:
        return builder(result, check, check.inputs)
    except (KeyError, TypeError, ValueError):
        return None


def _all(values: dict, *keys: str) -> bool:
    return all(values.get(k) is not None for k in keys)


def _disagreement(result: StructuredEvidenceResult, keys) -> Optional[str]:
    """"Excluded population disagrees: 8 vs 9" - built from the conflicting fact."""
    parts = []
    for key in keys:
        fact = result.fact(key)
        if fact is None or not fact.conflict:
            continue
        values = " vs ".join(str(value) for value, _ in fact.conflicting_values)
        parts.append(f"{fact.label} disagrees: {values}")
    return "; ".join(parts) or None


def _population(result, check, values) -> Optional[str]:
    if check.state == SUPPORTED and _all(values, "source_population",
                                         "excluded_population", "reviewed_population"):
        return (f"{values['source_population']} accounts extracted, "
                f"{values['excluded_population']} excluded, "
                f"{values['reviewed_population']} reviewed - reconciled")
    if check.state == CONFLICT and _all(values, "source_population",
                                        "excluded_population", "reviewed_population"):
        expected = values["source_population"] - values["excluded_population"]
        return (f"Population does not reconcile: {values['source_population']} "
                f"extracted minus {values['excluded_population']} excluded is "
                f"{expected}, but {values['reviewed_population']} were reviewed")
    if check.state == NEEDS_REVIEW:
        found = _disagreement(result, ("source_population", "excluded_population",
                                       "reviewed_population"))
        return f"Population cannot be reconciled - {found}" if found else None
    if check.state == MISSING:
        return "Population counts are not stated in this artifact"
    return None


_DECISION_KEYS = ("decision_retain", "decision_modify", "decision_revoke",
                  "decision_investigate")


def _decisions(result, check, values) -> Optional[str]:
    if check.state == SUPPORTED and _all(values, *_DECISION_KEYS, "reviewed_population"):
        return (f"All {values['reviewed_population']} reviewed accounts carry a "
                f"reviewer decision (retain {values['decision_retain']}, modify "
                f"{values['decision_modify']}, revoke {values['decision_revoke']}, "
                f"investigate {values['decision_investigate']})")
    if check.state == CONFLICT and _all(values, *_DECISION_KEYS, "reviewed_population"):
        total = sum(values[k] for k in _DECISION_KEYS)
        return (f"Decisions total {total} but {values['reviewed_population']} accounts "
                f"were reviewed")
    if check.state == NEEDS_REVIEW:
        found = _disagreement(result, _DECISION_KEYS + ("reviewed_population",))
        return f"Decisions cannot be reconciled - {found}" if found else None
    if check.state == MISSING:
        return "Reviewer decision counts are not stated in this artifact"
    return None


def _remediation(result, check, values) -> Optional[str]:
    required = values.get("remediation_required")
    completed = values.get("remediation_completed")
    computed = values.get("remediation_open_computed")
    if required is not None and completed is not None and computed is not None:
        if check.state == SUPPORTED:
            return (f"All {required} flagged access changes are recorded as "
                    f"completed - 0 unresolved")
        if check.state == PARTIALLY_SUPPORTED:
            return (f"{required} access changes flagged, {completed} completed - "
                    f"{computed} unresolved")
        if check.state == CONFLICT:
            stated = values.get("remediation_open")
            if stated is not None:
                return (f"{required} flagged and {completed} completed leaves "
                        f"{computed} unresolved, but the artifact states {stated}")
            return (f"{completed} completions recorded against only {required} "
                    f"flagged access changes")
    if check.state == NEEDS_REVIEW:
        found = _disagreement(result, ("decision_revoke", "decision_modify",
                                       "remediation_completed", "remediation_open"))
        return f"Open remediation cannot be computed - {found}" if found else None
    if check.state == MISSING:
        return "Remediation closure counts are not stated in this artifact"
    return None


def _post_change(result, check, values) -> Optional[str]:
    if check.state == SUPPORTED:
        return "Post-change system confirmation is present for remediated items"
    if check.state == PARTIALLY_SUPPORTED:
        return ("Ticket references are present, but no post-change confirmation "
                "in this artifact")
    if check.state == MISSING:
        return "No closure record or post-change confirmation in this artifact"
    return None


def _identity(result, check, values) -> Optional[str]:
    populations = values.get("identity_populations")
    if isinstance(populations, dict) and populations:
        covered = ", ".join(f"{name} {count}" for name, count in sorted(populations.items()))
        if check.state == SUPPORTED:
            return f"Population covers {covered}"
        if check.state == PARTIALLY_SUPPORTED:
            absent = [t for t in EXPECTED_IDENTITY_TYPES if t not in populations]
            if absent:
                return (f"Population covers {covered}, but shows no "
                        f"{' or '.join(absent)} accounts")
    if check.state == MISSING:
        return "The population is not broken down by identity type in this artifact"
    return None


def _period_line(result, check, values) -> Optional[str]:
    if check.state == SUPPORTED and _all(values, "review_period_start",
                                         "review_period_end"):
        return (f"Review period {values['review_period_start']} to "
                f"{values['review_period_end']}")
    if check.state == MISSING:
        return "No review period or completion date in this artifact"
    return None


def _exceptions_line(result, check, values) -> Optional[str]:
    count = values.get("exceptions_open")
    if count is not None:
        if check.state == PARTIALLY_SUPPORTED:
            return f"{count} exception(s) recorded as unresolved in this artifact"
        if check.state == SUPPORTED:
            return "No unresolved exceptions recorded"
    if check.state == MISSING:
        return "No exception or open-item count is stated in this artifact"
    return None


def _consistency(result, check, values) -> Optional[str]:
    if check.state == SUPPORTED:
        return "Every fact read from this artifact appears with one consistent value"
    keys = values.get("conflicting_facts") or ()
    return _disagreement(result, keys)


_BUILDERS = {
    CHECK_POPULATION: _population,
    CHECK_DECISIONS: _decisions,
    CHECK_REMEDIATION: _remediation,
    CHECK_POST_CHANGE: _post_change,
    CHECK_IDENTITY: _identity,
    CHECK_PERIOD: _period_line,
    CHECK_EXCEPTIONS: _exceptions_line,
    CHECK_CONSISTENCY: _consistency,
}


def fact_display(fact: EvidenceFact) -> Any:
    """Value as shown in the facts table; a contradicted fact shows no value."""
    if fact.conflict:
        return None
    if fact.unit == "breakdown" and fact.value:
        return ", ".join(f"{name} {count}" for name, count in fact.value)
    return fact.value
