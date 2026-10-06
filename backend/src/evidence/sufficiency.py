#!/usr/bin/env python3
"""CP009.1: deterministic evidence sufficiency observations, not control verdicts.

Unknown assessment boundaries are explicitly NOT_EVALUATED. Matching an evidence
ID establishes relevance of the artifact type, never implementation or execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .backbone import EvidenceAnalysis, ArtifactProvenance
from .mapping import MappingView, QuestionEvidence, REQUEST, REVIEW, PARTIAL, OBSERVED, NOT_EVALUATED as MAP_UNEVALUATED

SCHEMA_VERSION = '1.0.0'
DIMENSIONS = ('presence', 'relevance', 'scope', 'period', 'completeness',
              'execution', 'provenance', 'consistency')
STATES = frozenset(('ESTABLISHED', 'PARTIALLY_ESTABLISHED', 'NOT_ESTABLISHED',
                    'REQUIRES_REVIEW', 'NOT_APPLICABLE', 'NOT_EVALUATED'))


@dataclass(frozen=True)
class DimensionResult:
    dimension: str
    state: str
    supporting_facts: tuple[str, ...]
    missing_facts: tuple[str, ...]
    reason: str
    provenance: tuple[ArtifactProvenance, ...]
    next_action: str

    def __post_init__(self):
        if self.dimension not in DIMENSIONS or self.state not in STATES or not self.reason:
            raise ValueError('Invalid sufficiency dimension, state or empty reason')

    def to_dict(self):
        return dict(dimension=self.dimension, state=self.state,
                    supporting_facts=list(self.supporting_facts), missing_facts=list(self.missing_facts),
                    reason=self.reason, provenance=[p.to_dict() for p in self.provenance],
                    next_action=self.next_action)


@dataclass(frozen=True)
class RequirementSufficiency:
    question_id: str
    related_controls: tuple[str, ...]
    dimensions: tuple[DimensionResult, ...]

    def __post_init__(self):
        if tuple(d.dimension for d in self.dimensions) != DIMENSIONS:
            raise ValueError('Exactly eight ordered dimensions are required')

    def to_dict(self):
        return dict(question_id=self.question_id, related_controls=list(self.related_controls),
                    dimensions=[d.to_dict() for d in self.dimensions])


@dataclass(frozen=True)
class SufficiencyView:
    questionnaire_id: str
    requirements: tuple[RequirementSufficiency, ...]

    def to_dict(self):
        return dict(record_type='evidence_sufficiency', schema_version=SCHEMA_VERSION,
                    questionnaire_id=self.questionnaire_id,
                    requirements=[r.to_dict() for r in self.requirements])


def evaluate_sufficiency(analysis: EvidenceAnalysis, mapping: MappingView,
                         *, assessment_scope: Optional[str] = None,
                         assessment_period: Optional[str] = None) -> SufficiencyView:
    """Assess observable sufficiency dimensions; never extrapolate a compliance result.

    Scope/period arguments identify requested boundaries only: until there is an
    authoritative comparison rule, matching them remains NOT_EVALUATED.
    """
    artifacts = {a.artifact_id: a for a in analysis.artifacts}
    requirements = []
    for q in mapping.questions:
        matched = tuple(artifacts[l.artifact_id] for l in q.links
                        if l.artifact_id in artifacts and
                        artifacts[l.artifact_id].knowledge_evidence_id in q.expected_evidence)
        provenance = tuple(dict.fromkeys(p for a in matched for f in a.facts for p in f.provenance))
        keys = tuple(sorted({f.key for a in matched for f in a.facts if f.provenance}))
        conflicts = any(f.conflict for a in matched for f in a.facts) or any(
            c.state == 'CONFLICT' for a in matched for c in a.checks)
        flagged = any(a.needs_review for a in matched)
        incomplete = any(c.state != 'SUPPORTED' for a in matched for c in a.checks)
        def dim(name, state, reason, missing=(), action='', facts=keys, sources=provenance):
            return DimensionResult(name, state, facts, tuple(missing), reason, sources, action)
        if q.state == MAP_UNEVALUATED:
            dimensions = tuple(dim(name, 'NOT_EVALUATED',
                                   'Question is outside the verified deterministic mapping slice.',
                                   facts=(), sources=()) for name in DIMENSIONS)
        else:
            presence = dim('presence', 'ESTABLISHED' if matched else 'NOT_ESTABLISHED',
                'At least one expected classified evidence type was submitted.' if matched else
                'No submitted artifact is classified as an expected evidence type; this does not imply control failure.',
                () if matched else q.expected_evidence, '' if matched else q.next_action,
                facts=keys if matched else (), sources=provenance if matched else ())
            relevance = dim('relevance', 'ESTABLISHED' if matched else 'NOT_ESTABLISHED',
                'Classification matches an authoritative questionnaire expected-evidence ID; substantive sufficiency is separate.' if matched else
                'No authoritative expected-evidence ID match.',
                () if matched else q.expected_evidence, '' if matched else q.next_action,
                facts=keys if matched else (), sources=provenance if matched else ())
            scope = dim('scope', 'NOT_EVALUATED',
                'No validated rule compares extracted population to the requested assessment scope.' if assessment_scope else
                'Applicable assessment population/systems were not supplied.',
                (assessment_scope,) if assessment_scope else ('assessment scope',),
                'Provide the authoritative scope and population reconciliation.')
            period = dim('period', 'NOT_EVALUATED',
                'No validated period-coverage comparison rule is available.' if assessment_period else
                'Requested assessment period was not supplied.',
                (assessment_period,) if assessment_period else ('assessment period',),
                'Provide the requested assessment period and verify coverage.')
            completeness = dim('completeness', 'REQUIRES_REVIEW' if flagged else
                'PARTIALLY_ESTABLISHED' if incomplete else 'NOT_EVALUATED',
                'Artifact-level validation flags require review.' if flagged else
                'One or more artifact-level checks are not supported.' if incomplete else
                'No authoritative requirement-level completeness rule has been defined.',
                ('requirement-level completeness',), 'Reconcile applicable population and outstanding source checks.')
            execution = dim('execution', 'NOT_EVALUATED',
                'An expected evidence type or policy statement alone does not prove operating execution.',
                ('independently verified execution',), 'Validate execution using applicable source records.')
            prov = dim('provenance', 'ESTABLISHED' if matched and keys and provenance else
                'REQUIRES_REVIEW' if matched else 'NOT_ESTABLISHED',
                'Extracted supporting facts have source locators.' if matched and keys and provenance else
                'Matching artifact has no fully traceable supporting facts.' if matched else
                'No matching submitted source to trace.',
                () if matched and keys and provenance else ('traceable supporting facts',),
                '' if matched and keys and provenance else 'Obtain source-level fact locators.')
            consistency = dim('consistency', 'REQUIRES_REVIEW' if conflicts else 'NOT_EVALUATED',
                'A source fact/check is explicitly flagged as conflicting.' if conflicts else
                'Cross-artifact consistency has not been verified; absence of flagged conflicts is not proof of consistency.',
                ('conflict reconciliation',) if conflicts else ('cross-artifact comparison',),
                'Preserve and compare relevant source records.' if conflicts else 'Perform cross-artifact comparison.')
            dimensions = (presence, relevance, scope, period, completeness, execution, prov, consistency)
        requirements.append(RequirementSufficiency(q.question_id, q.related_controls, dimensions))
    return SufficiencyView(mapping.questionnaire_id, tuple(requirements))
