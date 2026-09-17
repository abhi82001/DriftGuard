#!/usr/bin/env python3
"""XLSX/CSV -> structure -> classify -> extract -> validate -> result (CP007 Phase 1).

The pipeline is the only place the stages are joined. Extraction never validates
and validation never extracts, so replacing the deterministic extractor with a
future model-backed one changes what is read, never what is concluded.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .classify import (
    KNOWLEDGE_EVIDENCE_ID,
    UNCLASSIFIED,
    USER_ACCESS_REVIEW,
    Classification,
    classify,
)
from .extractors import base as extractor_registry
from .extractors import user_access_review as _uar  # noqa: F401  (registers extractor)
from .model import (
    CONFLICT,
    MISSING,
    NEEDS_REVIEW,
    NOT_A_FAILURE,
    EvidenceFact,
    StructuredEvidenceResult,
    aggregate_state,
)
from .tabular import TabularError, is_tabular, read_tabular
from .validation import validate_user_access_review

VALIDATORS = {USER_ACCESS_REVIEW: validate_user_access_review}

UNCLASSIFIED_NOTE = (
    "This file was not recognised as a supported evidence type, so no structured "
    "facts were read from it. An unrecognised artifact is unread material, not a "
    "negative result about any control."
)


def analyze_evidence_file(
    filename: str,
    data: bytes,
    extractor: Optional[extractor_registry.EvidenceExtractor] = None,
) -> StructuredEvidenceResult:
    """Run the full pipeline over one tabular upload. Never raises on bad input."""
    if not is_tabular(filename):
        return _unreadable(filename, f"{filename} is not an XLSX or CSV file")
    try:
        workbook = read_tabular(filename, data)
    except TabularError as exc:
        return _unreadable(filename, str(exc))

    classification = classify(workbook)
    if not classification.supported:
        return StructuredEvidenceResult(
            filename=filename, evidence_type=UNCLASSIFIED,
            knowledge_evidence_id="", state=MISSING, needs_review=False,
            notes=(UNCLASSIFIED_NOTE,
                   f"signal groups not found: {', '.join(classification.missing_groups)}"),
            classification_confidence=classification.confidence,
            matched_signals=classification.matched_signals,
        )

    chosen = extractor or extractor_registry.get(classification.evidence_type)
    if chosen is None:
        return _unreadable(
            filename,
            f"no extractor is registered for {classification.evidence_type}",
        )

    facts = tuple(chosen.extract(workbook, classification))
    checks, derived = VALIDATORS[classification.evidence_type](facts)
    facts = facts + derived

    state = aggregate_state(tuple(c.state for c in checks))
    needs_review = any(c.state in (NEEDS_REVIEW, CONFLICT) for c in checks)

    return StructuredEvidenceResult(
        filename=filename,
        evidence_type=classification.evidence_type,
        knowledge_evidence_id=KNOWLEDGE_EVIDENCE_ID[classification.evidence_type],
        state=state,
        needs_review=needs_review,
        facts=facts,
        checks=checks,
        notes=(NOT_A_FAILURE,),
        classification_confidence=classification.confidence,
        matched_signals=classification.matched_signals,
        extractor=getattr(chosen, "source", type(chosen).__name__),
    )


def analyze_evidence(
    files: Iterable[tuple[str, bytes]],
) -> list[StructuredEvidenceResult]:
    """Analyse every tabular upload; non-tabular files are left to CP006."""
    return [
        analyze_evidence_file(filename, data)
        for filename, data in files
        if is_tabular(filename)
    ]


def _unreadable(filename: str, reason: str) -> StructuredEvidenceResult:
    return StructuredEvidenceResult(
        filename=filename, evidence_type=UNCLASSIFIED, knowledge_evidence_id="",
        state=NEEDS_REVIEW, needs_review=True,
        notes=(reason, NOT_A_FAILURE),
    )


__all__ = [
    "Classification",
    "EvidenceFact",
    "StructuredEvidenceResult",
    "analyze_evidence",
    "analyze_evidence_file",
]
