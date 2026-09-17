#!/usr/bin/env python3
"""Structured evidence result model (CP007 Phase 1).

These records describe what an uploaded artifact *shows*, never whether a SOC 2
control passed. The support states are evidence states: they say how well the
artifact supports its own assertions, and nothing about compliance. Missing
material is reported as MISSING, which is an absence of evidence and never a
control failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ------------------------------------------------------------- support states
SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
MISSING = "MISSING"
CONFLICT = "CONFLICT"
NEEDS_REVIEW = "NEEDS_REVIEW"

EVIDENCE_STATES = (SUPPORTED, PARTIALLY_SUPPORTED, MISSING, CONFLICT, NEEDS_REVIEW)

# Ordered worst-first for aggregation. CONFLICT and NEEDS_REVIEW always win:
# DriftGuard must not silently pick a winner between disagreeing numbers.
_AGGREGATION_ORDER = (CONFLICT, NEEDS_REVIEW, PARTIALLY_SUPPORTED, MISSING, SUPPORTED)

NOT_A_FAILURE = (
    "Absent or incomplete material is reported as missing evidence. It is not a "
    "control failure and not a compliance conclusion."
)


@dataclass(frozen=True)
class Provenance:
    """Where in the uploaded file a fact actually came from."""

    filename: str
    sheet: str
    locator: str          # "B10" | "row 4" | "rows 2-113 column F"
    excerpt: str = ""

    def __str__(self) -> str:
        return f"{self.filename} / {self.sheet} / {self.locator}"

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "sheet": self.sheet,
            "locator": self.locator,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class EvidenceFact:
    """One normalized fact read out of the artifact.

    `value` is None exactly when `conflict` is True: two places in the artifact
    state different values for the same fact and DriftGuard does not choose one.
    """

    key: str
    label: str
    value: Any
    unit: str                                  # count | date | text | breakdown | flag
    derivation: str                            # stated | counted | stated+counted | computed
    provenance: tuple[Provenance, ...] = ()
    conflict: bool = False
    conflicting_values: tuple[tuple[Any, Provenance], ...] = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "derivation": self.derivation,
            "conflict": self.conflict,
            "conflicting_values": [
                {"value": v, "provenance": p.to_dict()} for v, p in self.conflicting_values
            ],
            "provenance": [p.to_dict() for p in self.provenance],
        }


@dataclass(frozen=True)
class ValidationCheck:
    """One deterministic reconciliation performed in DriftGuard code.

    `grounding` names the knowledge record (and validation rule where one
    applies) that makes the check meaningful. No check invents a requirement.
    """

    check_id: str
    name: str
    state: str
    detail: str
    inputs: dict = field(default_factory=dict)
    grounding: str = ""
    provenance: tuple[Provenance, ...] = ()

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "state": self.state,
            "detail": self.detail,
            "inputs": dict(self.inputs),
            "grounding": self.grounding,
            "provenance": [p.to_dict() for p in self.provenance],
        }


@dataclass(frozen=True)
class StructuredEvidenceResult:
    filename: str
    evidence_type: str                 # USER_ACCESS_REVIEW | UNCLASSIFIED
    knowledge_evidence_id: str         # existing knowledge ID, never invented
    state: str
    needs_review: bool
    facts: tuple[EvidenceFact, ...] = ()
    checks: tuple[ValidationCheck, ...] = ()
    notes: tuple[str, ...] = ()
    classification_confidence: float = 0.0
    matched_signals: tuple[str, ...] = ()
    extractor: str = ""

    def fact(self, key: str) -> Optional[EvidenceFact]:
        return next((f for f in self.facts if f.key == key), None)

    def value(self, key: str) -> Any:
        f = self.fact(key)
        return None if f is None else f.value

    def check(self, check_id: str) -> Optional[ValidationCheck]:
        return next((c for c in self.checks if c.check_id == check_id), None)

    @property
    def conflicting_facts(self) -> tuple[EvidenceFact, ...]:
        return tuple(f for f in self.facts if f.conflict)

    def to_dict(self) -> dict:
        return {
            "record_type": "structured_evidence_result",
            "filename": self.filename,
            "evidence_type": self.evidence_type,
            "knowledge_evidence_id": self.knowledge_evidence_id,
            "state": self.state,
            "needs_review": self.needs_review,
            "classification_confidence": self.classification_confidence,
            "matched_signals": list(self.matched_signals),
            "extractor": self.extractor,
            "facts": [f.to_dict() for f in self.facts],
            "checks": [c.to_dict() for c in self.checks],
            "notes": list(self.notes),
        }


def aggregate_state(states: tuple[str, ...]) -> str:
    """Roll check states up into one evidence state.

    A disagreement or an unresolvable input dominates everything else; a clean
    artifact with nothing missing is the only way to reach SUPPORTED.
    """
    if not states:
        return MISSING
    for candidate in _AGGREGATION_ORDER:
        if candidate in states:
            # MISSING alone (no positives at all) stays MISSING; mixed with any
            # positive signal it is a partial picture, not an absent one.
            if candidate is MISSING and any(s == SUPPORTED for s in states):
                return PARTIALLY_SUPPORTED
            return candidate
    return MISSING
