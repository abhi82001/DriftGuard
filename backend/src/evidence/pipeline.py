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
from .structured_registry import SCHEMAS, recognize, analyze_register
from .operational_registers import analyze_operational, recognize_operational

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
    *, as_of=None, workbook=None,
) -> StructuredEvidenceResult:
    """Run the full pipeline over one tabular upload. Never raises on bad input.

    `workbook` lets a caller that already parsed the file (the job's classify stage) skip the re-read."""
    if not is_tabular(filename):
        return _unreadable(filename, f"{filename} is not an XLSX or CSV file")
    if workbook is None:
        try:
            workbook = read_tabular(filename, data)
        except TabularError as exc:
            return _unreadable(filename, str(exc))

    classification = classify(workbook)
    if not classification.supported:
        # Exact register schemas stay authoritative; operational exports are matched
        # by header synonyms only when no exact schema fits.
        exact = any(set(sp.required) <= set(sh.headers) for sh in workbook.sheets for sp in SCHEMAS)
        operational = None if exact else recognize_operational(workbook)
        if operational is not None:
            return analyze_operational(workbook, operational[0], operational[1], as_of=as_of)
        register = recognize(workbook)
        if register is not None:
            spec, sheet = register
            return analyze_register(workbook, spec, sheet, as_of=as_of)
    if not classification.supported:
        return StructuredEvidenceResult(
            filename=filename, evidence_type=UNCLASSIFIED,
            knowledge_evidence_id="", state=MISSING, needs_review=True,
            notes=(UNCLASSIFIED_NOTE,
                   ("ISSUE EQA-UNSUPPORTED-TYPE: Only a recognized schema has a structured "
                    "extractor/validator in this release. The access-review signal groups "
                    "are not applicable validation criteria for other artifact types. "
                    "No structured assurance was performed; retain the original upload "
                    "and route to a type-specific validator or manual review.")),
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
    *, as_of=None, workbooks=None,
) -> list[StructuredEvidenceResult]:
    """Analyse every tabular upload; non-tabular files are left to CP006."""
    workbooks = workbooks or {}
    return [
        analyze_evidence_file(filename, data, as_of=as_of, workbook=workbooks.get(filename))
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
