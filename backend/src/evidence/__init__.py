"""Structured evidence intelligence (CP007 Phase 1).

Turns an uploaded XLSX/CSV audit artifact into validated structured facts with
provenance, before any SOC 2 assessment happens. Phase 1 supports exactly one
evidence type, USER_ACCESS_REVIEW, grounded in the existing EV-ACCESS-001
knowledge record.

Layering (extraction is deliberately separate from validation):

    tabular      -> sheets, headers, addressable cells
    classify     -> evidence type, only when structurally supported
    extractors   -> normalized facts + provenance (pluggable; no arithmetic)
    validation   -> deterministic reconciliation in DriftGuard code
    pipeline     -> joins the stages into a StructuredEvidenceResult

Nothing here asserts a compliance conclusion, and missing material is always
reported as missing evidence rather than as a control failure.
"""

from .classify import (
    KNOWLEDGE_EVIDENCE_ID,
    UNCLASSIFIED,
    USER_ACCESS_REVIEW,
    Classification,
    classify,
)
from .extractors.base import EvidenceExtractor, register
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
    StructuredEvidenceResult,
    ValidationCheck,
    aggregate_state,
)
from .pipeline import analyze_evidence, analyze_evidence_file
from .report import (
    EXCEPTION_ORDER,
    NO_EXCEPTIONS,
    STATE_WORDS,
    EvidenceReport,
    ReportLine,
    build_report,
    fact_display,
)
from .tabular import TabularError, Workbook, is_tabular, read_tabular

__all__ = [
    "CONFLICT",
    "Classification",
    "EVIDENCE_STATES",
    "EXCEPTION_ORDER",
    "EvidenceReport",
    "NO_EXCEPTIONS",
    "ReportLine",
    "STATE_WORDS",
    "build_report",
    "fact_display",
    "EvidenceExtractor",
    "EvidenceFact",
    "KNOWLEDGE_EVIDENCE_ID",
    "MISSING",
    "NEEDS_REVIEW",
    "NOT_A_FAILURE",
    "PARTIALLY_SUPPORTED",
    "Provenance",
    "SUPPORTED",
    "StructuredEvidenceResult",
    "TabularError",
    "UNCLASSIFIED",
    "USER_ACCESS_REVIEW",
    "ValidationCheck",
    "Workbook",
    "aggregate_state",
    "analyze_evidence",
    "analyze_evidence_file",
    "classify",
    "is_tabular",
    "read_tabular",
    "register",
]
