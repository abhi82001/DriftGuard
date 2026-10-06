#!/usr/bin/env python3
"""Canonical evidence-analysis backbone (CP008).

This module joins the existing CP006 document/claim path and CP007 structured
(tabular) evidence path without replacing either one.  File format is kept
separate from evidence type: readers turn bytes into addressable document
chunks, while evidence-specific analyzers add grounded facts and deterministic
checks.

Nothing in this layer decides SOC 2 compliance.  It records what an artifact
shows, where it was found, how it was derived, and whether the artifact itself
needs review.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from claims import ClaimExtractor, DemoClaimExtractor, SecurityClaim
from ingestion import Document, IngestionError, extract

from .classify import UNCLASSIFIED
from .model import StructuredEvidenceResult
from .pipeline import analyze_evidence_file
from .tabular import is_tabular

DOCUMENT_TEXT = "DOCUMENT_TEXT"
STRUCTURED_EVIDENCE = "STRUCTURED_EVIDENCE"


@dataclass(frozen=True)
class ArtifactProvenance:
    """A format-neutral pointer back to uploaded source material."""

    filename: str
    locator: str
    excerpt: str = ""
    container: str = ""  # sheet name for tabular evidence; blank otherwise

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "container": self.container,
            "locator": self.locator,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class ArtifactFact:
    """One grounded fact exposed through the common evidence contract."""

    key: str
    label: str
    value: Any
    nature: str
    derivation: str
    provenance: tuple[ArtifactProvenance, ...] = ()
    source_layer: str = ""
    conflict: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "nature": self.nature,
            "derivation": self.derivation,
            "source_layer": self.source_layer,
            "conflict": self.conflict,
            "provenance": [p.to_dict() for p in self.provenance],
        }


@dataclass(frozen=True)
class ArtifactCheck:
    """A deterministic artifact-level validation, never a control verdict."""

    check_id: str
    name: str
    state: str
    detail: str
    grounding: str = ""
    provenance: tuple[ArtifactProvenance, ...] = ()

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "state": self.state,
            "detail": self.detail,
            "grounding": self.grounding,
            "provenance": [p.to_dict() for p in self.provenance],
        }


@dataclass(frozen=True)
class EvidenceArtifact:
    """The common result consumed by future evidence-to-control reasoning."""

    artifact_id: str
    filename: str
    format: str
    document_kind: str
    evidence_type: str
    knowledge_evidence_id: str
    state: str
    needs_review: bool
    facts: tuple[ArtifactFact, ...] = ()
    checks: tuple[ArtifactCheck, ...] = ()
    notes: tuple[str, ...] = ()
    analyzers: tuple[str, ...] = ()
    chunk_count: int = 0

    def facts_for(self, key: str) -> tuple[ArtifactFact, ...]:
        return tuple(f for f in self.facts if f.key == key)

    def to_dict(self) -> dict:
        return {
            "record_type": "evidence_artifact",
            "artifact_id": self.artifact_id,
            "filename": self.filename,
            "format": self.format,
            "document_kind": self.document_kind,
            "evidence_type": self.evidence_type,
            "knowledge_evidence_id": self.knowledge_evidence_id,
            "state": self.state,
            "needs_review": self.needs_review,
            "chunk_count": self.chunk_count,
            "analyzers": list(self.analyzers),
            "facts": [f.to_dict() for f in self.facts],
            "checks": [c.to_dict() for c in self.checks],
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class EvidenceAnalysis:
    """One upload batch after all currently available evidence readers ran."""

    artifacts: tuple[EvidenceArtifact, ...]
    errors: tuple[str, ...] = ()

    def artifact(self, filename: str) -> Optional[EvidenceArtifact]:
        return next((a for a in self.artifacts if a.filename == filename), None)

    @property
    def needs_review(self) -> tuple[EvidenceArtifact, ...]:
        return tuple(a for a in self.artifacts if a.needs_review)

    def to_dict(self) -> dict:
        return {
            "record_type": "evidence_analysis",
            "artifacts": [a.to_dict() for a in self.artifacts],
            "errors": list(self.errors),
        }


def analyze_artifacts(
    files: Iterable[tuple[str, bytes]],
    claim_extractor: Optional[ClaimExtractor] = None,
) -> EvidenceAnalysis:
    """Analyze mixed supported uploads through one canonical evidence API.

    CP006 still owns local format extraction and conservative claim extraction.
    CP007 still owns structured XLSX/CSV classification, fact extraction and
    reconciliation.  This function only adapts their grounded outputs into one
    contract, so neither path has to know about the other.
    """
    extractor = claim_extractor or DemoClaimExtractor()
    artifacts: list[EvidenceArtifact] = []
    errors: list[str] = []

    for filename, data in files:
        try:
            document = extract(filename, data)
        except IngestionError as exc:
            errors.append(str(exc))
            continue

        claims = extractor.extract((document,))
        structured = analyze_evidence_file(filename, data) if is_tabular(filename) else None
        artifacts.append(_build_artifact(
            filename, data, document, claims, structured,
            getattr(extractor, "source", type(extractor).__name__),
        ))

    return EvidenceAnalysis(tuple(artifacts), tuple(errors))


def _build_artifact(
    filename: str,
    data: bytes,
    document: Document,
    claims: list[SecurityClaim],
    structured: Optional[StructuredEvidenceResult],
    claim_analyzer: str,
) -> EvidenceArtifact:
    claim_facts = tuple(_claim_facts(claims))
    structured_facts = tuple(_structured_facts(structured)) if structured else ()
    checks = tuple(_structured_checks(structured)) if structured else ()

    if structured is not None:
        evidence_type = structured.evidence_type
        knowledge_id = structured.knowledge_evidence_id
        # CP007 being unable to classify a tabular artifact must not erase
        # grounded CP006 observations from that same file.
        state = (
            "OBSERVED"
            if structured.evidence_type == UNCLASSIFIED and claim_facts
            else structured.state
        )
        needs_review = structured.needs_review
        notes = structured.notes
    else:
        # Unstructured CP006 claims are observations, not a validated evidence
        # type.  They remain unclassified until an evidence-specific analyzer
        # can establish what the artifact is.
        evidence_type = UNCLASSIFIED
        knowledge_id = ""
        state = "OBSERVED" if claim_facts else "UNREAD"
        needs_review = False
        notes = ()

    analyzers = ["cp006-document-reader"]
    if claims:
        analyzers.append(claim_analyzer)
    if structured is not None:
        analyzers.append(structured.extractor or "cp007-structured-evidence")

    return EvidenceArtifact(
        artifact_id=_artifact_id(filename, data),
        filename=filename,
        format=_format(filename),
        document_kind=document.kind,
        evidence_type=evidence_type,
        knowledge_evidence_id=knowledge_id,
        state=state,
        needs_review=needs_review,
        facts=claim_facts + structured_facts,
        checks=checks,
        notes=tuple(notes),
        analyzers=tuple(dict.fromkeys(analyzers)),
        chunk_count=len(document.chunks),
    )


def _claim_facts(claims: list[SecurityClaim]):
    for claim in claims:
        provenance = (ArtifactProvenance(
            filename=claim.source_filename,
            locator=claim.source_locator,
            excerpt=claim.snippet,
        ),)
        for attribute, value in claim.attributes.items():
            yield ArtifactFact(
                key=f"{claim.topic}.{attribute}",
                label=attribute.replace("_", " "),
                value=value,
                nature=claim.evidence_nature,
                derivation="extracted",
                provenance=provenance,
                source_layer=DOCUMENT_TEXT,
            )


def _structured_facts(result: StructuredEvidenceResult):
    for fact in result.facts:
        yield ArtifactFact(
            key=fact.key,
            label=fact.label,
            value=fact.value,
            nature="STRUCTURED_RECORD",
            derivation=fact.derivation,
            provenance=tuple(
                ArtifactProvenance(p.filename, p.locator, p.excerpt, p.sheet)
                for p in fact.provenance
            ),
            source_layer=STRUCTURED_EVIDENCE,
            conflict=fact.conflict,
        )


def _structured_checks(result: StructuredEvidenceResult):
    for check in result.checks:
        yield ArtifactCheck(
            check_id=check.check_id,
            name=check.name,
            state=check.state,
            detail=check.detail,
            grounding=check.grounding,
            provenance=tuple(
                ArtifactProvenance(p.filename, p.locator, p.excerpt, p.sheet)
                for p in check.provenance
            ),
        )


def _artifact_id(filename: str, data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(filename.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    digest.update(data)
    return digest.hexdigest()[:16]


def _format(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".") or "unknown"


__all__ = [
    "DOCUMENT_TEXT",
    "STRUCTURED_EVIDENCE",
    "ArtifactCheck",
    "ArtifactFact",
    "ArtifactProvenance",
    "EvidenceAnalysis",
    "EvidenceArtifact",
    "analyze_artifacts",
]
