import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ['DRIFTGUARD_DEMO_MODE']='1'
from evidence.backbone import EvidenceAnalysis, EvidenceArtifact, ArtifactFact, ArtifactProvenance, analyze_artifacts
from evidence.mapping import map_questionnaire
from evidence.intelligence import build_intelligence, semantic_fallback, cross_artifact_consistency

def test_missing_requests_are_grounded_and_deterministic():
    a=EvidenceAnalysis(())
    x=build_intelligence(a,map_questionnaire(a))
    assert x==build_intelligence(a,map_questionnaire(a))
    requests=x['technical_view']['evidence_requests']
    assert any(r['evidence_id']=='EV-IAM-001' for r in requests)
    assert all(r['questions'] and r['controls'] and r['source_gap'] for r in requests)
    assert x['organization_view']['requirements_not_evaluated']>0

def test_policy_does_not_prove_enforcement():
    a=analyze_artifacts([('policy.txt',b'MFA is mandatory for all users.')])
    x=build_intelligence(a,map_questionnaire(a))
    q=next(r for r in x['technical_view']['sufficiency']['requirements'] if r['question_id']=='QN-ACCESS-001-Q01')
    d={d['dimension']:d['state'] for d in q['dimensions']}
    assert d['presence']=='NOT_ESTABLISHED' and d['execution']=='NOT_EVALUATED'

def test_semantic_fallback_requires_approval_and_grounding():
    assert semantic_fallback('weird','original',('account_id',))['state']=='CLARIFICATION_REQUIRED'
    class Provider:
        def propose(self,**kwargs):
            return dict(canonical_field='account_id',supporting_text='made up',rationale='x',clarification='')
    assert semantic_fallback('weird','original',('account_id',),Provider())['state']=='REJECTED'
    class Grounded:
        def propose(self,**kwargs):
            return dict(canonical_field='account_id',supporting_text='original',rationale='x',clarification='')
    assert semantic_fallback('weird','original',('account_id',),Grounded())['state']=='HUMAN_APPROVAL_REQUIRED'

def _artifact(id,value):
    p=ArtifactProvenance(id+'.csv','A2',str(value))
    facts=tuple(ArtifactFact(k,k,v,'observation','extracted',(p,)) for k,v in
        [('entity_id','user1'),('assessment_scope','prod'),('assessment_period','Q3'),('mfa_enabled',value)])
    return EvidenceArtifact(id,id+'.csv','csv','STRUCTURED_EVIDENCE','TEST','', 'OBSERVED',False,facts)

def test_consistency_preserves_both_sources():
    a=EvidenceAnalysis((_artifact('a',True),_artifact('b',False)))
    findings=cross_artifact_consistency(a)
    conflict=next(x for x in findings if x['fact_key']=='mfa_enabled')
    assert conflict['state']=='POTENTIAL_INCONSISTENCY'
    assert {o['artifact_id'] for o in conflict['observations']}=={'a','b'}
    assert any(f['fact_key']=='mfa_enabled' and f['state']=='CONSISTENT' for f in cross_artifact_consistency(EvidenceAnalysis((_artifact('a',True),_artifact('b',True))))) 

def test_real_access_review_fixture():
    path=Path(__file__).parent/'fixtures/files/Q3_Access_Review.xlsx'
    a=analyze_artifacts([(path.name,path.read_bytes())])
    x=build_intelligence(a,map_questionnaire(a))
    assert x['schema_version']=='1.0.0'
    assert x['technical_view']['relationship_graph']['nodes']
    assert x['organization_view']['evidence_available']==1

def test_api_serialization_and_real_fixture():
    import asyncio, httpx
    from app import app
    path=Path(__file__).parent/'fixtures/files/Q3_Access_Review.xlsx'
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/api/evidence-map',files=[('files',(path.name,path.read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))])
            assert response.status_code==200
            data=response.json()['intelligence']
            assert data['organization_view']['evidence_available']==1
            assert len(data['technical_view']['sufficiency']['requirements'])>0
            assert all('provenance' in d for r in data['technical_view']['sufficiency']['requirements'] for d in r['dimensions'])
    asyncio.run(check())

def test_output_schema():
    import json, jsonschema
    root=Path(__file__).resolve().parents[1]
    schema=json.loads((root/'schemas/control_intelligence.v1.schema.json').read_text())
    a=EvidenceAnalysis(())
    jsonschema.validate(build_intelligence(a,map_questionnaire(a)),schema)


def test_semantic_provider_failure_degrades_safely():
    class Broken:
        def propose(self, **kwargs):
            raise TimeoutError('secret details must not be exposed')
    result = semantic_fallback('unknown', 'source', ('known',), Broken())
    assert result['state'] == 'CLARIFICATION_REQUIRED'
    assert 'secret details' not in str(result)
    assert semantic_fallback('x', 'x' * 20001, ('known',), Broken())['state'] == 'CLARIFICATION_REQUIRED'
