import json, time, zipfile
from pathlib import Path
import pytest
from driftguard_platform.ai import AIRequest, AIResult, AIOperation, DisabledAIProvider, AIUnavailable, AIValidationError, validate_result, AIRegistry
from driftguard_platform.facts import CanonicalFact, FactSource, deduplicate_facts
from driftguard_platform.intelligence import classify_unknown, extract_candidate_facts
from driftguard_platform.policy import PolicyRequirement, evaluate_requirement
from driftguard_platform.privacy import evaluate_privacy_facts
from driftguard_platform.frameworks import registry as frameworks
from driftguard_platform.enterprise import ServiceCredential, authorize, sign_webhook, verify_webhook, idempotency_key
from driftguard_platform.byoai import TenantAIConfig, provider_for
from driftguard_platform.assistant import AssistantContext, grounded_answer
from driftguard_platform.auditor import AuditTrace
from driftguard_platform.production import inspect_upload

class Fake:
    name='fake'
    def __init__(self,data,confidence=.9): self.data=data; self.confidence=confidence
    def execute(self,request): return AIResult(request.operation,self.data,self.name,'fake-1',request.source_ids,self.confidence,correlation_id=request.correlation_id)

def test_disabled_ai_fails_closed():
    with pytest.raises(AIUnavailable): DisabledAIProvider().execute(AIRequest(AIOperation.CLASSIFY,'x'))

def test_prohibited_ai_verdict_rejected():
    with pytest.raises(AIValidationError): validate_result(AIResult(AIOperation.CLASSIFY,{'answer':'COMPLIANT'},'fake','x',('a',),.9))

def test_grounded_operation_requires_source():
    with pytest.raises(AIValidationError): validate_result(AIResult(AIOperation.EXTRACT,{'facts':[]},'fake','x',(),.9))

def test_deterministic_classification_wins_above_threshold():
    c=classify_unknown(Fake({'artifact_type':'WRONG'}),content='x',source_id='a',deterministic_type='ASSET_INVENTORY',deterministic_confidence=.95)
    assert c.artifact_type=='ASSET_INVENTORY'

def test_ai_fallback_classifies_unknown():
    c=classify_unknown(Fake({'artifact_type':'PRIVACY_CONSENT_REGISTER'}),content='consent withdrawal purpose',source_id='a')
    assert c.artifact_type=='PRIVACY_CONSENT_REGISTER' and c.confidence==.9

def test_ai_fact_without_locator_is_rejected():
    facts=extract_candidate_facts(Fake({'facts':[{'subject':'u1','predicate':'MFA','value':True}]}),content='x',source_id='a')
    assert facts==()

def test_ai_fact_has_provenance():
    facts=extract_candidate_facts(Fake({'facts':[{'subject':'u1','predicate':'MFA','value':True,'locator':'row 2'}]}),content='x',source_id='a')
    assert facts[0].source.locator=='row 2' and facts[0].extraction_method=='ai'

def test_fact_deduplication_prefers_confidence():
    s=FactSource('a','row 1'); a=CanonicalFact('u','MFA',True,s,confidence=.4); b=CanonicalFact('u','MFA',True,s,confidence=.9,extraction_method='ai')
    assert deduplicate_facts([a,b])==(b,)

def test_policy_sla_boundary_and_exception():
    src=FactSource('policy','p.1'); op=FactSource('evidence','row 2'); r=PolicyRequirement('R1','request','DAYS','lte',30,src,'days')
    assert evaluate_requirement(r,30,op).state=='OPERATING_EVIDENCED'
    assert evaluate_requirement(r,31,op).state=='EXCEPTION_IDENTIFIED'
    assert evaluate_requirement(r,None,None).state=='INSUFFICIENT_EVIDENCE'

def test_privacy_slas():
    s=FactSource('privacy','row 3'); facts=[CanonicalFact('req','RIGHTS_REQUEST_DAYS',46,s),CanonicalFact('breach','BREACH_NOTIFICATION_HOURS',240,s)]
    codes={x.code for x in evaluate_privacy_facts(facts)}
    assert {'RIGHTS-SLA','BREACH-SLA'}<=codes

def test_framework_registry_is_versioned():
    assert frameworks.get('SOC2','2017').key=='SOC2'
    assert frameworks.get('DPDP','2023').version=='2023'

def test_tenant_authorization():
    c=ServiceCredential('c','tenant-a',frozenset({'evidence:read'})); authorize(c,'tenant-a','evidence:read')
    with pytest.raises(PermissionError): authorize(c,'tenant-b','evidence:read')

def test_webhook_signing_and_replay_window():
    p=b'{}'; ts=1000; sig=sign_webhook('secret',ts,p)
    assert verify_webhook('secret',ts,p,sig,now=1100)
    assert not verify_webhook('secret',ts,p,sig,now=2000)
    assert not verify_webhook('wrong',ts,p,sig,now=1100)

def test_idempotency_stable(): assert idempotency_key('t',{'a':1})==idempotency_key('t',{'a':1})

def test_byoai_disabled_default():
    p=provider_for(TenantAIConfig('t'),AIRegistry()); assert isinstance(p,DisabledAIProvider)

def test_grounded_assistant_refuses_without_sources():
    assert 'sufficient evidence' in grounded_answer(Fake({'answer':'bad'}),'why',AssistantContext('t',(),(),{}))

def test_grounded_assistant_uses_existing_assessment():
    ans=grounded_answer(Fake({'answer':'Partial because one item is open.'}),'why',AssistantContext('t',('e1',),({'x':1},),{'state':'PARTIAL'}))
    assert 'Partial' in ans

def test_audit_trace_requires_evidence():
    with pytest.raises(ValueError): AuditTrace('SOC2','CC6','r',(),('f',),'PARTIAL').validate()

def test_upload_inspection_rejects_path_traversal(tmp_path):
    p=tmp_path/'bad.zip'
    with zipfile.ZipFile(p,'w') as z:z.writestr('../escape.txt','x')
    assert not inspect_upload(p).safe

def test_upload_hash_is_stable(tmp_path):
    p=tmp_path/'a.txt';p.write_text('hello'); a=inspect_upload(p); b=inspect_upload(p)
    assert a.safe and a.sha256==b.sha256

def test_dpdp_structural_schemas_are_semantic_not_idp():
    from evidence.tabular import read_tabular
    from evidence.structured_registry import recognize
    cases={
      'consent.csv':b'principal_id,purpose,consent_obtained_on,consent_status,withdrawn_on,withdrawal_processed_on,is_child,parental_consent\nP1,analytics,2026-01-01,active,,,false,false\n',
      'rights.csv':b'record_id,type,received_on,acknowledged_on,closed_on,notes\nR1,erasure,2026-01-01,2026-01-02,2026-01-03,done\n',
      'processors.csv':b'processor,personal_data_processed,contract_has_dpdp_clauses,last_assurance_review,country\nV1,email,true,2026-01-01,IN\n'}
    expected={'consent.csv':'PRIVACY_CONSENT_REGISTER','rights.csv':'PRIVACY_RIGHTS_BREACH_LOG','processors.csv':'PRIVACY_PROCESSOR_ASSESSMENT'}
    for name,data in cases.items():
        spec,_=recognize(read_tabular(name,data)); assert spec.kind==expected[name]

def test_okta_reference_connector_normalizes_without_leaking_token():
    from driftguard_platform.integrations import OktaConnector
    class Resp:
        status_code=200; headers={}
        def json(self): return [{'id':'00u1','status':'ACTIVE','profile':{'email':'a@example.com','login':'a@example.com'},'lastUpdated':'2026-01-01'}]
        def raise_for_status(self): pass
    class Client:
        def get(self,*a,**kw): return Resp()
    c=OktaConnector('https://example.okta.com','super-secret',Client())
    assert c.test_connection()
    r=c.collect(); assert r.records[0].kind=='IDENTITY_PROVIDER_EXPORT'
    assert 'super-secret' not in repr(r)

def test_okta_connector_rejects_insecure_endpoint():
    from driftguard_platform.integrations import OktaConnector
    with pytest.raises(ValueError): OktaConnector('http://okta.local','x')
