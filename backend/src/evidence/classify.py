#!/usr/bin/env python3
"""Deterministic evidence-type classification (CP007 Phase 1).

Phase 1 recognises exactly one evidence type, USER_ACCESS_REVIEW, and only when
the artifact's own *structure* announces it: sheet names, header labels and
key/value labels. Body text is deliberately not scanned, so a spreadsheet that
merely mentions users cannot be mistaken for a review campaign export.

Anything not sufficiently supported stays UNCLASSIFIED. An unclassified upload
is an unread artifact, never a negative result about a control.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Provenance
from .tabular import Sheet, Workbook, column_letter, normalize

USER_ACCESS_REVIEW = "USER_ACCESS_REVIEW"
UNCLASSIFIED = "UNCLASSIFIED"

# The evidence type maps onto an existing knowledge record; no ID is invented.
KNOWLEDGE_EVIDENCE_ID = {USER_ACCESS_REVIEW: "EV-ACCESS-001"}

# Four independent signal groups. A group counts once however often it matches.
_SIGNAL_GROUPS: dict[str, tuple[str, ...]] = {
    "review_campaign": (
        "access review", "user access review", "entitlement review",
        "access certification", "recertification", "review campaign",
        "campaign status", "campaign name", "review period", "review decision",
        "reviewed / certified accounts", "review completed date",
    ),
    "decision": (
        "retain", "revoke", "revoked", "modify", "investigate", "certify",
        "certified", "decision",
    ),
    "identity_population": (
        "account id", "accounts", "identity type", "account type",
        "entitlement", "service account", "privileged", "reviewed accounts",
        "source population",
    ),
    "remediation": (
        "remediation", "remediation status", "remediation ticket",
        "exception", "open items", "closure",
    ),
}

# A review must announce itself as a review; the other groups corroborate it.
_REQUIRED_GROUP = "review_campaign"
_MIN_GROUPS = 3


@dataclass(frozen=True)
class Classification:
    evidence_type: str
    confidence: float
    matched_groups: tuple[str, ...]
    matched_signals: tuple[str, ...]
    missing_groups: tuple[str, ...]
    provenance: tuple[Provenance, ...] = ()

    @property
    def supported(self) -> bool:
        return self.evidence_type != UNCLASSIFIED


def _structural_text(sheet: Sheet) -> list[tuple[str, Provenance]]:
    """Sheet name, header labels and first-column labels, with provenance."""
    out: list[tuple[str, Provenance]] = [(
        normalize(sheet.name),
        Provenance(sheet.filename, sheet.name, "sheet name", sheet.name),
    )]
    for text, column in zip(sheet.headers, sheet.header_columns):
        out.append((text, Provenance(
            sheet.filename, sheet.name,
            f"{column_letter(column)}{sheet.header_row}", text,
        )))
    for row in sheet.rows:
        first = row.cell(1)
        if first is not None and isinstance(first.value, str) and not first.empty:
            out.append((normalize(first.text), Provenance(
                sheet.filename, sheet.name, first.ref, first.text,
            )))
    return out


def classify(workbook: Workbook) -> Classification:
    matched_groups: dict[str, Provenance] = {}
    matched_signals: dict[str, Provenance] = {}

    for sheet in workbook.sheets:
        for text, provenance in _structural_text(sheet):
            if not text:
                continue
            for group, signals in _SIGNAL_GROUPS.items():
                for signal in signals:
                    if signal in text:
                        matched_signals.setdefault(signal, provenance)
                        matched_groups.setdefault(group, provenance)

    groups = tuple(g for g in _SIGNAL_GROUPS if g in matched_groups)
    missing = tuple(g for g in _SIGNAL_GROUPS if g not in matched_groups)
    confidence = round(len(groups) / len(_SIGNAL_GROUPS), 2)
    supported = _REQUIRED_GROUP in matched_groups and len(groups) >= _MIN_GROUPS

    return Classification(
        evidence_type=USER_ACCESS_REVIEW if supported else UNCLASSIFIED,
        confidence=confidence,
        matched_groups=groups,
        matched_signals=tuple(sorted(matched_signals)),
        missing_groups=missing,
        provenance=tuple(matched_groups[g] for g in groups),
    )
