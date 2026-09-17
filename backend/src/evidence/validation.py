#!/usr/bin/env python3
"""Deterministic reconciliation of extracted evidence facts (CP007 Phase 1).

Every calculation here runs in DriftGuard code. No model is consulted, and no
check produces a compliance verdict: a check says how well the artifact supports
its own numbers, which is a statement about evidence, not about a control.

Three rules are observed throughout:

  * a fact whose sources disagree is never resolved automatically - the check
    that depends on it becomes NEEDS_REVIEW;
  * an absent fact is MISSING, which is missing evidence and never a failure;
  * open remediation is surfaced as a number, not as a judgement.
"""

from __future__ import annotations

from typing import Optional

from evaluation.semantic import PROHIBITED_VERDICTS

from .classify import KNOWLEDGE_EVIDENCE_ID, USER_ACCESS_REVIEW
from .knowledge import grounding
from .model import (
    CONFLICT,
    EVIDENCE_STATES,
    MISSING,
    NEEDS_REVIEW,
    NOT_A_FAILURE,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    EvidenceFact,
    Provenance,
    ValidationCheck,
)

EVIDENCE_ID = KNOWLEDGE_EVIDENCE_ID[USER_ACCESS_REVIEW]

CHECK_POPULATION = "POP-RECON"
CHECK_DECISIONS = "DEC-RECON"
CHECK_DECISION_COVERAGE = "DEC-COVERAGE"
CHECK_REMEDIATION = "REM-CLOSURE"
CHECK_POST_CHANGE = "REM-CONFIRMATION"
CHECK_IDENTITY = "POP-COVERAGE"
CHECK_PERIOD = "REVIEW-PERIOD"
CHECK_EXCEPTIONS = "OPEN-ITEMS"
CHECK_CONSISTENCY = "FACT-CONSISTENCY"

# Populations whose omission is the classic scope defect for this artifact
# (EV-ACCESS-001 expected_content).
EXPECTED_IDENTITY_TYPES = ("privileged", "service_account")

DERIVED_OPEN_REMEDIATION = "remediation_open_computed"


class _Facts:
    def __init__(self, facts: tuple[EvidenceFact, ...]):
        self._by_key = {f.key: f for f in facts}

    def get(self, key: str) -> Optional[EvidenceFact]:
        return self._by_key.get(key)

    def value(self, key: str):
        fact = self._by_key.get(key)
        return None if fact is None or fact.conflict else fact.value

    def conflicted(self, *keys: str) -> tuple[str, ...]:
        return tuple(k for k in keys if (f := self._by_key.get(k)) is not None and f.conflict)

    def absent(self, *keys: str) -> tuple[str, ...]:
        return tuple(k for k in keys if self._by_key.get(k) is None)

    def provenance(self, *keys: str) -> tuple[Provenance, ...]:
        out: list[Provenance] = []
        for key in keys:
            fact = self._by_key.get(key)
            if fact is not None:
                out.extend(fact.provenance)
        return tuple(out)


def validate_user_access_review(
    facts: tuple[EvidenceFact, ...],
) -> tuple[tuple[ValidationCheck, ...], tuple[EvidenceFact, ...]]:
    """Run the deterministic checks. Returns (checks, facts derived by them)."""
    f = _Facts(facts)
    checks: list[ValidationCheck] = []
    derived: list[EvidenceFact] = []

    checks.append(_population(f))
    checks.append(_decisions(f))
    checks.append(_decision_coverage(f))
    remediation_check, remediation_fact = _remediation(f)
    checks.append(remediation_check)
    if remediation_fact is not None:
        derived.append(remediation_fact)
    checks.append(_post_change(f))
    checks.append(_identity_coverage(f))
    checks.append(_period(f))
    checks.append(_exceptions(f))
    checks.append(_consistency(facts))

    for check in checks:
        _guard(check)
    return tuple(checks), tuple(derived)


# ------------------------------------------------------------------- checks
def _population(f: _Facts) -> ValidationCheck:
    keys = ("source_population", "excluded_population", "reviewed_population")
    name = "population reconciliation"
    ground = grounding(EVIDENCE_ID, "VR-002")
    inputs = {k: f.value(k) for k in keys}
    provenance = f.provenance(*keys)

    conflicted = f.conflicted(*keys)
    if conflicted:
        return ValidationCheck(
            CHECK_POPULATION, name, NEEDS_REVIEW,
            f"The artifact states more than one value for {', '.join(conflicted)}, so "
            f"source - excluded = reviewed cannot be reconciled. DriftGuard does not "
            f"choose between them; a human must.",
            inputs, ground, provenance,
        )
    absent = f.absent(*keys)
    if absent:
        return ValidationCheck(
            CHECK_POPULATION, name, MISSING,
            f"Not stated in the artifact: {', '.join(absent)}. {NOT_A_FAILURE}",
            inputs, ground, provenance,
        )

    source, excluded, reviewed = (inputs[k] for k in keys)
    expected = source - excluded
    if expected == reviewed:
        return ValidationCheck(
            CHECK_POPULATION, name, SUPPORTED,
            f"source_population {source} - excluded_population {excluded} = "
            f"reviewed_population {reviewed}.",
            inputs, ground, provenance,
        )
    return ValidationCheck(
        CHECK_POPULATION, name, CONFLICT,
        f"source_population {source} - excluded_population {excluded} = {expected}, "
        f"but reviewed_population is {reviewed} (difference {reviewed - expected}). "
        f"The artifact's own numbers disagree.",
        inputs, ground, provenance,
    )


def _decisions(f: _Facts) -> ValidationCheck:
    decision_keys = ("decision_retain", "decision_modify", "decision_revoke",
                     "decision_investigate")
    keys = decision_keys + ("reviewed_population",)
    name = "reviewer decision reconciliation"
    ground = grounding(EVIDENCE_ID, "VR-002")
    inputs = {k: f.value(k) for k in keys}
    provenance = f.provenance(*keys)

    conflicted = f.conflicted(*keys)
    if conflicted:
        return ValidationCheck(
            CHECK_DECISIONS, name, NEEDS_REVIEW,
            f"The artifact states more than one value for {', '.join(conflicted)}, so "
            f"the decision counts cannot be reconciled to the reviewed population.",
            inputs, ground, provenance,
        )
    absent = f.absent(*keys)
    if absent:
        return ValidationCheck(
            CHECK_DECISIONS, name, MISSING,
            f"Not stated in the artifact: {', '.join(absent)}. {NOT_A_FAILURE}",
            inputs, ground, provenance,
        )

    total = sum(inputs[k] for k in decision_keys)
    reviewed = inputs["reviewed_population"]
    parts = " + ".join(f"{k.split('_', 1)[1]} {inputs[k]}" for k in decision_keys)
    if total == reviewed:
        return ValidationCheck(
            CHECK_DECISIONS, name, SUPPORTED,
            f"{parts} = {total}, matching reviewed_population {reviewed}.",
            inputs, ground, provenance,
        )
    return ValidationCheck(
        CHECK_DECISIONS, name, CONFLICT,
        f"{parts} = {total}, but reviewed_population is {reviewed} "
        f"(difference {total - reviewed}). The artifact's own numbers disagree.",
        inputs, ground, provenance,
    )


def _decision_coverage(f: _Facts) -> ValidationCheck:
    """Does every reviewed row carry a decision DriftGuard could read?

    The extractor counts the rows it could not place instead of dropping them,
    so this check can say how much of the population the decision counts above
    actually describe. An unreadable value is not a wrong decision: it is a
    value DriftGuard declines to interpret, which is a matter for a human.
    """
    name = "reviewer decision coverage"
    ground = grounding(EVIDENCE_ID, "VR-002")
    fact = f.get("decision_unrecognized")
    provenance = f.provenance("decision_unrecognized")

    if fact is None:
        return ValidationCheck(
            CHECK_DECISION_COVERAGE, name, MISSING,
            f"No reviewer decision column was found in this artifact, so rows "
            f"without a recognised decision cannot be counted from it. "
            f"{NOT_A_FAILURE}",
            {}, ground, provenance,
        )
    if fact.conflict:
        return ValidationCheck(
            CHECK_DECISION_COVERAGE, name, NEEDS_REVIEW,
            "The artifact states more than one count of rows without a recognised "
            "reviewer decision.",
            {}, ground, provenance,
        )

    reviewed = f.value("reviewed_population")
    inputs = {"decision_unrecognized": fact.value, "reviewed_population": reviewed}
    if not fact.value:
        of_population = f" of {reviewed}" if reviewed is not None else ""
        return ValidationCheck(
            CHECK_DECISION_COVERAGE, name, SUPPORTED,
            f"Every reviewed row{of_population} carries a reviewer decision "
            f"DriftGuard recognises.",
            inputs, ground, provenance,
        )

    where = ", ".join(f"{p.locator} ({p.excerpt})" for p in provenance)
    of_population = f" of {reviewed}" if reviewed is not None else ""
    return ValidationCheck(
        CHECK_DECISION_COVERAGE, name, NEEDS_REVIEW,
        f"{fact.value} reviewed row(s){of_population} carry a decision value "
        f"DriftGuard does not recognise, at {where}. The rows are counted rather "
        f"than discarded, and DriftGuard does not decide what those values mean; "
        f"a human must.",
        inputs, ground, provenance,
    )


def _remediation(f: _Facts) -> tuple[ValidationCheck, Optional[EvidenceFact]]:
    """Open remediation = items the reviewer flagged for change, minus those closed."""
    name = "remediation closure"
    ground = grounding(EVIDENCE_ID, "VR-003")
    actionable_keys = ("decision_revoke", "decision_modify")
    keys = actionable_keys + ("remediation_completed", "remediation_open")
    inputs = {k: f.value(k) for k in keys}
    provenance = f.provenance(*keys)

    conflicted = f.conflicted(*keys)
    if conflicted:
        return ValidationCheck(
            CHECK_REMEDIATION, name, NEEDS_REVIEW,
            f"The artifact states more than one value for {', '.join(conflicted)}, so "
            f"open remediation cannot be computed.",
            inputs, ground, provenance,
        ), None

    actionable = [inputs[k] for k in actionable_keys if inputs[k] is not None]
    completed = inputs["remediation_completed"]
    if not actionable or completed is None:
        absent = f.absent("remediation_completed") or ("decisions flagged for change",)
        return ValidationCheck(
            CHECK_REMEDIATION, name, MISSING,
            f"Not stated in the artifact: {', '.join(absent)}. {NOT_A_FAILURE}",
            inputs, ground, provenance,
        ), None

    required = sum(actionable)
    computed_open = required - completed
    inputs = dict(inputs, remediation_required=required,
                  remediation_open_computed=computed_open)
    derived = EvidenceFact(
        key=DERIVED_OPEN_REMEDIATION,
        label="remediation open (computed)",
        value=computed_open, unit="count", derivation="computed",
        provenance=provenance,
    )

    if computed_open < 0:
        return ValidationCheck(
            CHECK_REMEDIATION, name, CONFLICT,
            f"remediation_completed {completed} exceeds the {required} items flagged "
            f"for change (revoke/modify). The artifact's own numbers disagree.",
            inputs, ground, provenance,
        ), derived

    stated_open = inputs["remediation_open"]
    if stated_open is not None and stated_open != computed_open:
        return ValidationCheck(
            CHECK_REMEDIATION, name, CONFLICT,
            f"{required} items flagged for change minus {completed} completed leaves "
            f"{computed_open} open, but the artifact states {stated_open} open.",
            inputs, ground, provenance,
        ), derived

    if computed_open > 0:
        return ValidationCheck(
            CHECK_REMEDIATION, name, PARTIALLY_SUPPORTED,
            f"{required} items were flagged for change and {completed} are recorded as "
            f"completed, leaving {computed_open} open/unresolved remediation item(s). "
            f"Open items are reported as outstanding evidence of closure, not as a "
            f"control failure.",
            inputs, ground, provenance,
        ), derived

    return ValidationCheck(
        CHECK_REMEDIATION, name, SUPPORTED,
        f"All {required} items flagged for change are recorded as completed; "
        f"0 open/unresolved remediation items.",
        inputs, ground, provenance,
    ), derived


def _post_change(f: _Facts) -> ValidationCheck:
    """How many remediation rows actually carry a post-change confirmation.

    The presence of a confirmation column is no longer read as confirmation.
    The counted rows are, and an unconfirmed row is missing closure evidence
    rather than evidence of a control weakness.
    """
    name = "post-change confirmation present"
    ground = grounding(EVIDENCE_ID, "VR-003")
    count_keys = ("remediation_applicable_rows", "remediation_confirmed_rows",
                  "remediation_unconfirmed_rows")
    ticket = f.get("remediation_ticket_reference")
    provenance = f.provenance("remediation_ticket_reference", *count_keys)

    conflicted = f.conflicted(*count_keys)
    if conflicted:
        return ValidationCheck(
            CHECK_POST_CHANGE, name, NEEDS_REVIEW,
            f"The artifact states more than one value for {', '.join(conflicted)}, so "
            f"post-change confirmation cannot be counted.",
            {k: f.value(k) for k in count_keys}, ground, provenance,
        )

    applicable = f.value("remediation_applicable_rows")
    confirmed = f.value("remediation_confirmed_rows")
    if applicable is None or confirmed is None:
        # No post-change confirmation column at all: the artifact may still
        # carry ticket references, which is part of a closure record but not
        # confirmation that the change actually took effect.
        inputs = {"remediation_ticket_reference": ticket is not None,
                  "post_change_confirmation_column": False}
        if ticket is not None:
            return ValidationCheck(
                CHECK_POST_CHANGE, name, PARTIALLY_SUPPORTED,
                f"Ticket references are present but no post-change system confirmation "
                f"column was found. {NOT_A_FAILURE}",
                inputs, ground, provenance,
            )
        return ValidationCheck(
            CHECK_POST_CHANGE, name, MISSING,
            f"No closure record or post-change confirmation was found in this artifact. "
            f"{NOT_A_FAILURE}",
            inputs, ground, provenance,
        )

    inputs = {"remediation_ticket_reference": ticket is not None,
              **{k: f.value(k) for k in count_keys}}

    if applicable == 0:
        return ValidationCheck(
            CHECK_POST_CHANGE, name, SUPPORTED,
            "No row in this artifact records remediation activity, so there is "
            "nothing for a post-change confirmation to cover.",
            inputs, ground, provenance,
        )
    if confirmed == applicable:
        return ValidationCheck(
            CHECK_POST_CHANGE, name, SUPPORTED,
            f"All {applicable} row(s) recording remediation carry a post-change "
            f"confirmation.",
            inputs, ground, provenance,
        )
    if confirmed == 0:
        return ValidationCheck(
            CHECK_POST_CHANGE, name, MISSING,
            f"0 of {applicable} row(s) recording remediation carry a post-change "
            f"confirmation value DriftGuard recognises in this artifact. "
            f"{NOT_A_FAILURE}",
            inputs, ground, provenance,
        )
    return ValidationCheck(
        CHECK_POST_CHANGE, name, PARTIALLY_SUPPORTED,
        f"{confirmed} of {applicable} row(s) recording remediation carry a "
        f"post-change confirmation; {applicable - confirmed} row(s) do not. "
        f"{NOT_A_FAILURE}",
        inputs, ground, provenance,
    )


def _identity_coverage(f: _Facts) -> ValidationCheck:
    name = "identity population coverage"
    ground = grounding(EVIDENCE_ID, "VR-002")
    fact = f.get("identity_populations")
    if fact is None or fact.conflict:
        state = NEEDS_REVIEW if fact is not None else MISSING
        detail = (
            "The artifact states more than one identity population breakdown."
            if fact is not None else
            f"The artifact does not break the population down by identity type, so "
            f"coverage of {', '.join(EXPECTED_IDENTITY_TYPES)} accounts cannot be "
            f"determined from it. {NOT_A_FAILURE}"
        )
        return ValidationCheck(CHECK_IDENTITY, name, state, detail, {}, ground,
                               f.provenance("identity_populations"))

    present = {name_ for name_, _ in fact.value}
    inputs = {"identity_populations": dict(fact.value)}
    absent = tuple(t for t in EXPECTED_IDENTITY_TYPES if t not in present)
    if absent:
        return ValidationCheck(
            CHECK_IDENTITY, name, PARTIALLY_SUPPORTED,
            f"Identity types covered: {', '.join(sorted(present))}. Not represented: "
            f"{', '.join(absent)}. {NOT_A_FAILURE}",
            inputs, ground, fact.provenance,
        )
    return ValidationCheck(
        CHECK_IDENTITY, name, SUPPORTED,
        f"The reviewed population covers {', '.join(sorted(present))}.",
        inputs, ground, fact.provenance,
    )


def _period(f: _Facts) -> ValidationCheck:
    name = "review period stated"
    ground = grounding(EVIDENCE_ID, "VR-004")
    keys = ("review_period_start", "review_period_end", "review_completed_date")
    inputs = {k: f.value(k) for k in keys}
    provenance = f.provenance(*keys)
    conflicted = f.conflicted(*keys)
    if conflicted:
        return ValidationCheck(
            CHECK_PERIOD, name, NEEDS_REVIEW,
            f"The artifact states more than one value for {', '.join(conflicted)}.",
            inputs, ground, provenance,
        )
    stated = [k for k in keys if inputs[k]]
    if not stated:
        return ValidationCheck(
            CHECK_PERIOD, name, MISSING,
            f"No review period or completion date was found in this artifact. "
            f"{NOT_A_FAILURE}",
            inputs, ground, provenance,
        )
    if "review_period_start" in stated and "review_period_end" in stated:
        return ValidationCheck(
            CHECK_PERIOD, name, SUPPORTED,
            f"Review period {inputs['review_period_start']} to "
            f"{inputs['review_period_end']}.",
            inputs, ground, provenance,
        )
    return ValidationCheck(
        CHECK_PERIOD, name, PARTIALLY_SUPPORTED,
        f"Only part of the review timing is stated ({', '.join(stated)}). "
        f"{NOT_A_FAILURE}",
        inputs, ground, provenance,
    )


def _exceptions(f: _Facts) -> ValidationCheck:
    name = "open exceptions"
    ground = grounding(EVIDENCE_ID)
    fact = f.get("exceptions_open")
    provenance = f.provenance("exceptions_open")
    if fact is None:
        return ValidationCheck(
            CHECK_EXCEPTIONS, name, MISSING,
            f"The artifact does not state an exception or open-item count. "
            f"{NOT_A_FAILURE}",
            {}, ground, provenance,
        )
    if fact.conflict:
        return ValidationCheck(
            CHECK_EXCEPTIONS, name, NEEDS_REVIEW,
            "The artifact states more than one exception count.",
            {}, ground, provenance,
        )
    inputs = {"exceptions_open": fact.value}
    if fact.value:
        return ValidationCheck(
            CHECK_EXCEPTIONS, name, PARTIALLY_SUPPORTED,
            f"{fact.value} exception(s) / open item(s) are recorded as unresolved in "
            f"the artifact. Reported as outstanding, not as a control failure.",
            inputs, ground, provenance,
        )
    return ValidationCheck(
        CHECK_EXCEPTIONS, name, SUPPORTED,
        "The artifact records no unresolved exceptions.", inputs, ground, provenance,
    )


def _consistency(facts: tuple[EvidenceFact, ...]) -> ValidationCheck:
    name = "internal consistency of stated facts"
    ground = grounding(EVIDENCE_ID)
    conflicts = [f for f in facts if f.conflict]
    if not conflicts:
        return ValidationCheck(
            CHECK_CONSISTENCY, name, SUPPORTED,
            "Every fact read from this artifact has a single consistent value.",
            {}, ground,
        )
    detail_parts = []
    provenance: list[Provenance] = []
    for fact in conflicts:
        values = ", ".join(
            f"{value} at {p.sheet} {p.locator}" for value, p in fact.conflicting_values
        )
        detail_parts.append(f"{fact.key}: {values}")
        provenance.extend(fact.provenance)
    return ValidationCheck(
        CHECK_CONSISTENCY, name, CONFLICT,
        "The artifact states different values for the same fact in different places, "
        "and DriftGuard has not resolved the disagreement: " + "; ".join(detail_parts),
        {"conflicting_facts": [f.key for f in conflicts]}, ground, tuple(provenance),
    )


# -------------------------------------------------------------------- guard
def _guard(check: ValidationCheck) -> None:
    """A check may never carry a compliance verdict or an unknown state."""
    if check.state not in EVIDENCE_STATES:
        raise ValueError(f"{check.check_id} has unknown state {check.state!r}")
    blob = f"{check.state} {check.name} {check.detail}".upper()
    for banned in PROHIBITED_VERDICTS:
        if banned in blob:
            raise ValueError(f"{check.check_id} carries prohibited verdict {banned!r}")
