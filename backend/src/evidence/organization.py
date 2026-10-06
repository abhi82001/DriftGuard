#!/usr/bin/env python3
"""Organization-facing evidence operations built on the CP008 backbone.

This module turns artifact analysis into an actionable evidence workspace without
making SOC 2 compliance conclusions.  It answers operational questions teams
actually have: what did we receive, what needs human attention, where do sources
disagree, which concepts are evidenced more than once, and what should we ask
for next.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .backbone import EvidenceAnalysis, EvidenceArtifact, ArtifactProvenance
from .classify import UNCLASSIFIED


@dataclass(frozen=True)
class WorkItem:
    priority: str
    kind: str
    title: str
    detail: str
    artifact_ids: tuple[str, ...] = ()
    provenance: tuple[ArtifactProvenance, ...] = ()

    def to_dict(self) -> dict:
        return {
            "priority": self.priority, "kind": self.kind, "title": self.title,
            "detail": self.detail, "artifact_ids": list(self.artifact_ids),
            "provenance": [p.to_dict() for p in self.provenance],
        }


@dataclass(frozen=True)
class EvidenceVariance:
    fact_key: str
    nature: str
    values: tuple[Any, ...]
    artifact_ids: tuple[str, ...]
    provenance: tuple[ArtifactProvenance, ...]

    def to_dict(self) -> dict:
        return {
            "fact_key": self.fact_key, "nature": self.nature,
            "values": list(self.values), "artifact_ids": list(self.artifact_ids),
            "provenance": [p.to_dict() for p in self.provenance],
        }


@dataclass(frozen=True)
class ConceptCoverage:
    fact_key: str
    artifact_count: int
    artifact_ids: tuple[str, ...]
    filenames: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "fact_key": self.fact_key, "artifact_count": self.artifact_count,
            "artifact_ids": list(self.artifact_ids), "filenames": list(self.filenames),
        }


@dataclass(frozen=True)
class OrganizationEvidenceView:
    artifact_count: int
    recognized_count: int
    observed_unclassified_count: int
    unread_count: int
    review_count: int
    error_count: int
    work_items: tuple[WorkItem, ...]
    variances: tuple[EvidenceVariance, ...]
    reusable_concepts: tuple[ConceptCoverage, ...]

    def to_dict(self) -> dict:
        return {
            "record_type": "organization_evidence_view",
            "summary": {
                "artifact_count": self.artifact_count,
                "recognized_count": self.recognized_count,
                "observed_unclassified_count": self.observed_unclassified_count,
                "unread_count": self.unread_count,
                "review_count": self.review_count,
                "error_count": self.error_count,
            },
            "work_items": [x.to_dict() for x in self.work_items],
            "variances": [x.to_dict() for x in self.variances],
            "reusable_concepts": [x.to_dict() for x in self.reusable_concepts],
        }


def build_organization_view(analysis: EvidenceAnalysis) -> OrganizationEvidenceView:
    artifacts = analysis.artifacts
    work = list(_work_items(analysis))
    variances = tuple(_variances(artifacts))
    for variance in variances:
        work.append(WorkItem(
            "HIGH", "CROSS_ARTIFACT_VARIANCE",
            f"Review differing evidence for {variance.fact_key}",
            "Multiple artifacts of the same evidence nature contain different explicit values. "
            "DriftGuard does not choose a winner; confirm scope, period and source authority.",
            variance.artifact_ids, variance.provenance,
        ))

    return OrganizationEvidenceView(
        artifact_count=len(artifacts),
        recognized_count=sum(a.evidence_type != UNCLASSIFIED for a in artifacts),
        observed_unclassified_count=sum(
            a.evidence_type == UNCLASSIFIED and a.state == "OBSERVED" for a in artifacts
        ),
        unread_count=sum(a.state == "UNREAD" for a in artifacts),
        review_count=sum(a.needs_review for a in artifacts),
        error_count=len(analysis.errors),
        work_items=tuple(sorted(work, key=lambda x: (_priority(x.priority), x.kind, x.title))),
        variances=variances,
        reusable_concepts=tuple(_coverage(artifacts)),
    )


def _work_items(analysis: EvidenceAnalysis):
    for error in analysis.errors:
        yield WorkItem("HIGH", "INGESTION_ERROR", "Evidence could not be read", error)
    for a in analysis.artifacts:
        if a.state == "UNREAD":
            yield WorkItem("HIGH", "UNREAD_ARTIFACT", f"Review unread artifact: {a.filename}",
                           "No grounded evidence facts were extracted.", (a.artifact_id,))
        elif a.evidence_type == UNCLASSIFIED and a.facts:
            yield WorkItem("MEDIUM", "CLASSIFICATION_REVIEW",
                           f"Classify observed evidence: {a.filename}",
                           "Grounded facts were found, but no supported evidence-specific classifier established the artifact type.",
                           (a.artifact_id,), _artifact_provenance(a))
        if a.needs_review:
            yield WorkItem("HIGH", "ARTIFACT_REVIEW", f"Resolve evidence review: {a.filename}",
                           "The evidence-specific analyzer marked this artifact for human review.",
                           (a.artifact_id,), _artifact_provenance(a))
        for c in a.checks:
            if c.state in {"CONFLICT", "NEEDS_REVIEW"}:
                yield WorkItem("HIGH", "VALIDATION_EXCEPTION", c.name, c.detail,
                               (a.artifact_id,), c.provenance)
            elif c.state in {"MISSING", "PARTIALLY_SUPPORTED"}:
                yield WorkItem("MEDIUM", "EVIDENCE_FOLLOW_UP", c.name, c.detail,
                               (a.artifact_id,), c.provenance)


def _variances(artifacts: tuple[EvidenceArtifact, ...]):
    # Compare only like-for-like evidence nature. Policy statements and
    # implementation observations are intentionally not treated as equivalent.
    groups: dict[tuple[str, str], list[tuple[EvidenceArtifact, Any, tuple[ArtifactProvenance, ...]]]] = {}
    for a in artifacts:
        for f in a.facts:
            if f.conflict or f.value is None or isinstance(f.value, (dict, list, tuple, set)):
                continue
            groups.setdefault((f.key, f.nature), []).append((a, f.value, f.provenance))
    for (key, nature), rows in sorted(groups.items()):
        distinct = []
        for _, value, _ in rows:
            if value not in distinct:
                distinct.append(value)
        artifact_ids = tuple(dict.fromkeys(a.artifact_id for a, _, _ in rows))
        if len(distinct) > 1 and len(artifact_ids) > 1:
            provenance = tuple(p for _, _, prov in rows for p in prov)
            yield EvidenceVariance(key, nature, tuple(distinct), artifact_ids, provenance)


def _coverage(artifacts: tuple[EvidenceArtifact, ...]):
    groups: dict[str, list[EvidenceArtifact]] = {}
    for a in artifacts:
        for key in dict.fromkeys(f.key for f in a.facts):
            groups.setdefault(key, []).append(a)
    for key, rows in sorted(groups.items()):
        unique = list({a.artifact_id: a for a in rows}.values())
        if len(unique) > 1:
            yield ConceptCoverage(key, len(unique), tuple(a.artifact_id for a in unique),
                                  tuple(a.filename for a in unique))


def _artifact_provenance(a: EvidenceArtifact):
    return tuple(p for f in a.facts for p in f.provenance)


def _priority(value: str) -> int:
    return {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(value, 9)


__all__ = ["WorkItem", "EvidenceVariance", "ConceptCoverage", "OrganizationEvidenceView", "build_organization_view"]
