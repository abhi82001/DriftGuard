"""CP009.2-.6 conservative, source-addressable organization intelligence.

No inferred compliance outcomes, semantic proposals never mutate canonical facts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, Optional

from .backbone import EvidenceAnalysis
from .mapping import MappingView, NOT_EVALUATED
from .sufficiency import SufficiencyView, evaluate_sufficiency

VERSION = '1.0.0'


def _id(prefix, *parts):
    return prefix + '-' + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def evidence_requests(mapping: MappingView, sufficiency: SufficiencyView):
    """Deduplicate by requested evidence ID; keep all affected question/control IDs."""
    gaps = {}
    by_q = {r.question_id: r for r in sufficiency.requirements}
    for q in mapping.questions:
        if q.state == NOT_EVALUATED:
            continue
        dimensions = by_q[q.question_id].dimensions
        missing = next(d for d in dimensions if d.dimension == 'presence')
        if missing.state == 'NOT_ESTABLISHED':
            for evidence_id in missing.missing_facts:
                item = gaps.setdefault(('artifact', evidence_id), dict(kind='MISSING_ARTIFACT',
                    evidence_id=evidence_id, questions=set(), controls=set(),
                    missing_facts={evidence_id}, reason=missing.reason,
                    suggested_artifact=evidence_id, source_gap=f'{q.question_id}:presence',
                    priority='REQUIRED_EVIDENCE_MISSING', action=q.next_action, provenance=[]))
                item['questions'].add(q.question_id)
                item['controls'].update(q.related_controls)
        else:
            # Source checks are the authority for specific validation requests.
            for d in dimensions:
                if d.dimension in ('completeness', 'consistency', 'provenance') and d.state in ('REQUIRES_REVIEW', 'PARTIALLY_ESTABLISHED'):
                    key = ('validation', q.question_id, d.dimension)
                    gaps[key] = dict(kind='VALIDATION_OR_CLARIFICATION', evidence_id='',
                        questions={q.question_id}, controls=set(q.related_controls),
                        missing_facts=set(d.missing_facts), reason=d.reason,
                        suggested_artifact='Validated source record or clarification',
                        source_gap=f'{q.question_id}:{d.dimension}', priority='SOURCE_VALIDATION',
                        action=d.next_action, provenance=[p.to_dict() for p in d.provenance])
    out = []
    for key, item in sorted(gaps.items()):
        item['request_id'] = _id('REQ', key)
        for field in ('questions', 'controls', 'missing_facts'):
            item[field] = sorted(item[field])
        out.append(item)
    return out


def relationship_graph(analysis: EvidenceAnalysis, mapping: MappingView, requests):
    """Only authoritative question/control edges; facts are linked by exact artifact identity."""
    nodes, edges = {}, set()
    def node(kind, identifier, **attrs):
        nodes[(kind, identifier)] = dict(id=f'{kind}:{identifier}', kind=kind, **attrs)
        return f'{kind}:{identifier}'
    def edge(source, target, relation):
        edges.add((source, target, relation))
    facts_by_artifact = {}
    for artifact in analysis.artifacts:
        a = node('artifact', artifact.artifact_id, filename=artifact.filename)
        for index, fact in enumerate(artifact.facts):
            f = node('fact', f'{artifact.artifact_id}:{index}', key=fact.key,
                     provenance=[p.to_dict() for p in fact.provenance])
            edge(a, f, 'ESTABLISHES_OBSERVATION')
            facts_by_artifact.setdefault(artifact.artifact_id, []).append(f)
    for q in mapping.questions:
        question = node('question', q.question_id)
        for control in q.related_controls:
            edge(question, node('control', control), 'RELATED_TO_CONTROL')
        if q.state == NOT_EVALUATED:
            continue
        for evidence_id in q.expected_evidence:
            requirement = node('requirement', f'{q.question_id}:{evidence_id}', evidence_id=evidence_id)
            edge(requirement, question, 'REQUIRED_FOR_QUESTION')
            for link in q.links:
                artifact = next((a for a in analysis.artifacts if a.artifact_id == link.artifact_id), None)
                if artifact and artifact.knowledge_evidence_id == evidence_id:
                    for fact in facts_by_artifact.get(link.artifact_id, ()):
                        edge(fact, requirement, 'RELEVANT_OBSERVATION')
    for request in requests:
        gap = node('gap', request['source_gap'])
        edge(gap, node('request', request['request_id']), 'GENERATES_REQUEST')
        for qid in request['questions']:
            edge(gap, node('question', qid), 'GAP_FOR_QUESTION')
    return dict(nodes=[nodes[k] for k in sorted(nodes)], edges=[dict(source=a, target=b, relation=c) for a,b,c in sorted(edges)])


def cross_artifact_consistency(analysis: EvidenceAnalysis):
    """Compare observations only for identical fact key AND explicit matching entity/scope/period.

    Without these dimensions, differing observations are not safely comparable.
    """
    observations = {}
    for artifact in analysis.artifacts:
        metadata = {f.key: f.value for f in artifact.facts}
        for fact in artifact.facts:
            if not fact.provenance or fact.nature.lower() in ('policy', 'requirement'):
                continue
            entity = metadata.get('entity_id')
            scope = metadata.get('assessment_scope')
            period = metadata.get('assessment_period')
            if not all(isinstance(x, (str, int)) and str(x).strip() for x in (entity, scope, period)):
                continue
            observations.setdefault((fact.key, str(entity), str(scope), str(period)), []).append((artifact, fact))
    results = []
    for key, group in sorted(observations.items()):
        if len({a.artifact_id for a, _ in group}) < 2:
            continue
        values = {json.dumps(f.value, sort_keys=True, default=str) for _, f in group}
        state = 'POTENTIAL_INCONSISTENCY' if len(values) > 1 else 'CONSISTENT'
        results.append(dict(finding_id=_id('CONS', key), state=state, fact_key=key[0],
            entity=key[1], scope=key[2], period=key[3],
            observations=[dict(artifact_id=a.artifact_id, value=f.value,
                provenance=[p.to_dict() for p in f.provenance]) for a,f in group]))
    return results


class SemanticInterpreter(Protocol):
    def propose(self, *, unknown_term: str, source_text: str, known_concepts: tuple[str, ...]) -> dict: ...


def semantic_fallback(unknown_term: str, source_text: str, known_concepts: tuple[str, ...],
                      provider: Optional[SemanticInterpreter] = None):
    """Untrusted proposal is never accepted automatically; grounding is exact-substring based."""
    normalized = unknown_term.strip().casefold().replace('_', ' ').replace('-', ' ')
    matches = [c for c in known_concepts if c.casefold().replace('_', ' ').replace('-', ' ') == normalized]
    if len(matches) == 1:
        return dict(state='DETERMINISTIC_MATCH', canonical_field=matches[0])
    if provider is None:
        return dict(state='CLARIFICATION_REQUIRED', unknown_term=unknown_term,
                    request='Identify the canonical meaning of this source field.')
    if len(unknown_term) > 200 or len(source_text) > 20000 or len(known_concepts) > 500:
        return dict(state='CLARIFICATION_REQUIRED', reason='Semantic input exceeds configured safety bounds')
    try:
        proposal = provider.propose(unknown_term=unknown_term, source_text=source_text,
                                    known_concepts=known_concepts)
    except (Exception) as exc:  # Provider failure must not block deterministic assessment.
        return dict(state='CLARIFICATION_REQUIRED', reason='Semantic provider unavailable',
                    provider_error=type(exc).__name__)
    if not isinstance(proposal, dict) or set(proposal) != {'canonical_field', 'supporting_text', 'rationale', 'clarification'} or any(not isinstance(v, str) for v in proposal.values()):
        return dict(state='REJECTED', reason='Invalid proposal contract')
    if proposal['canonical_field'] not in known_concepts or not proposal['supporting_text'] or proposal['supporting_text'] not in source_text:
        return dict(state='REJECTED', reason='Unknown concept or ungrounded source text')
    return dict(state='HUMAN_APPROVAL_REQUIRED', proposal=proposal)


def build_intelligence(analysis: EvidenceAnalysis, mapping: MappingView, *, assessment_scope=None, assessment_period=None):
    suff = evaluate_sufficiency(analysis, mapping, assessment_scope=assessment_scope,
                                assessment_period=assessment_period)
    requests = evidence_requests(mapping, suff)
    graph = relationship_graph(analysis, mapping, requests)
    conflicts = cross_artifact_consistency(analysis)
    reuse = {}
    for q in mapping.questions:
        if q.state == NOT_EVALUATED:
            continue
        for link in q.links:
            reuse.setdefault(link.artifact_id, set()).add(q.question_id)
    reuse = [dict(artifact_id=k, question_ids=sorted(v)) for k,v in sorted(reuse.items()) if len(v) > 1]
    organization = dict(requirements_reviewed=sum(q.state != NOT_EVALUATED for q in mapping.questions),
        requirements_not_evaluated=sum(q.state == NOT_EVALUATED for q in mapping.questions),
        evidence_available=len(analysis.artifacts), evidence_requiring_validation=sum(a.needs_review for a in analysis.artifacts),
        missing_evidence=sum(r['kind'] == 'MISSING_ARTIFACT' for r in requests),
        potential_inconsistencies=sum(r['state'] == 'POTENTIAL_INCONSISTENCY' for r in conflicts),
        next_actions=[dict(request_id=r['request_id'], action=r['action'], questions=r['questions']) for r in requests],
        reuse_opportunities=reuse)
    return dict(record_type='control_intelligence', schema_version=VERSION,
        organization_view=organization, technical_view=dict(sufficiency=suff.to_dict(),
        evidence_requests=requests, relationship_graph=graph, consistency=conflicts),
        disclaimer='Submitted evidence and mappings are not SOC 2 compliance conclusions.')
