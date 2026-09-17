#!/usr/bin/env python3
"""Pluggable evidence-extraction boundary (CP007 Phase 1).

Extraction is deliberately separate from validation. An extractor only reports
what the artifact says, with provenance; it performs no arithmetic and reaches
no conclusion. That keeps a future LLM-backed extractor a drop-in replacement
for the deterministic one without ever letting a model decide anything about
compliance - the reconciliation that follows is DriftGuard code either way.
"""

from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

from ..classify import Classification
from ..model import EvidenceFact
from ..tabular import Workbook


@runtime_checkable
class EvidenceExtractor(Protocol):
    evidence_type: str
    source: str

    def extract(
        self, workbook: Workbook, classification: Classification
    ) -> list[EvidenceFact]:
        ...


_REGISTRY: dict[str, EvidenceExtractor] = {}


def register(extractor: EvidenceExtractor) -> EvidenceExtractor:
    """Register an extractor for its evidence type, replacing any previous one."""
    _REGISTRY[extractor.evidence_type] = extractor
    return extractor


def get(evidence_type: str) -> Optional[EvidenceExtractor]:
    return _REGISTRY.get(evidence_type)


def registered_types() -> Iterable[str]:
    return tuple(_REGISTRY)
