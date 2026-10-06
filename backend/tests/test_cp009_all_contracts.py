"""CP009 acceptance: every one of 29 contracts is exercised independently."""
import pytest
from claims import SecurityClaim
from documents import (DocumentAnalyzer, ESTABLISHED, PARTIAL, NOT_ESTABLISHED,
                       CLARIFICATION, CONFLICT, QUESTION_SPECS)
import app as webapp

QUESTIONS = {q['question_id']:(d['questionnaire_id'], d['name'], q)
             for d in webapp.KNOWLEDGE.questionnaires for q in d['questions']}
QIDS = sorted(QUESTIONS)

def claim(topic, attrs, role, file='evidence.txt', locator='section 1', evidence_date=''):
    return SecurityClaim(topic, 'grounded statement', file, locator,
                         'grounded supporting excerpt', role, attrs,
                         extraction_method='cp009-test-fixture', artifact_type=role, evidence_date=evidence_date)

def area(qid, claims):
    qn, name, q = QUESTIONS[qid]
    by={}
    for c in claims: by.setdefault(c.topic,[]).append(c)
    return DocumentAnalyzer(webapp.KNOWLEDGE)._area(qn, name, q, by)

def attrs(items, value=True): return {a:value for a,_ in items}

def test_all_29_questionnaire_records_have_real_contracts():
    assert set(QUESTION_SPECS) == set(QUESTIONS)
    assert len(QUESTION_SPECS) == 29

@pytest.mark.parametrize('qid', QIDS)
def test_contract_definition(qid):
    s=QUESTION_SPECS[qid]
    assert s.topic and (s.design or s.operating)
    assert len({a for a,_ in s.design+s.operating}) == len(s.design+s.operating)
    assert s.design_roles == frozenset({'POLICY','PROCEDURE'})
    assert s.operating_roles == frozenset({'OPERATING_EVIDENCE','CONFIGURATION','RECORD'})
    assert s.temporal_expectation and s.clarification_rule

@pytest.mark.parametrize('qid', QIDS)
def test_strong_positive(qid):
    s=QUESTION_SPECS[qid]; cs=[]
    if s.design: cs.append(claim(s.topic, attrs(s.design), 'POLICY','policy.txt'))
    if s.operating: cs.append(claim(s.topic, attrs(s.operating), 'RECORD','record.csv'))
    r=area(qid,cs)
    assert r.status == ESTABLISHED, (r.status,r.missing_facts)

@pytest.mark.parametrize('qid', QIDS)
def test_missing_evidence_is_not_failure(qid):
    r=area(qid,[])
    assert r.status == NOT_ESTABLISHED
    assert 'not a control failure' in r.reason

@pytest.mark.parametrize('qid', QIDS)
def test_partial_evidence(qid):
    s=QUESTION_SPECS[qid]
    if s.design:
        cs=[claim(s.topic, attrs(s.design),'POLICY')]
    else:
        cs=[claim(s.topic, attrs(s.operating[:1]),'RECORD')]
    r=area(qid,cs)
    assert r.status == PARTIAL
    assert r.missing_facts

@pytest.mark.parametrize('qid', QIDS)
def test_wrong_source_role_is_rejected(qid):
    s=QUESTION_SPECS[qid]; cs=[]
    if s.design: cs.append(claim(s.topic,attrs(s.design),'RECORD','wrong-record.csv'))
    if s.operating: cs.append(claim(s.topic,attrs(s.operating),'POLICY','wrong-policy.txt'))
    r=area(qid,cs)
    assert r.status == CLARIFICATION
    assert not r.known_facts

@pytest.mark.parametrize('qid', QIDS)
def test_material_conflict_is_surfaced(qid):
    s=QUESTION_SPECS[qid]; group=s.design or s.operating
    role='POLICY' if s.design else 'RECORD'; attr,_=group[0]
    r=area(qid,[claim(s.topic,{attr:'value-A'},role,'a.txt'),
                claim(s.topic,{attr:'value-B'},role,'b.txt')])
    assert r.status == CONFLICT
    assert 'disagree' in r.reason

@pytest.mark.parametrize('qid', QIDS)
def test_irrelevant_document_cannot_satisfy(qid):
    r=area(qid,[claim('irrelevant_security_topic',{'x':True},'POLICY')])
    assert r.status == NOT_ESTABLISHED
    assert not r.known_facts

@pytest.mark.parametrize('qid', QIDS)
def test_provenance_survives(qid):
    s=QUESTION_SPECS[qid]; group=s.design or s.operating
    role='POLICY' if s.design else 'RECORD'; attr,_=group[0]
    r=area(qid,[claim(s.topic,{attr:'grounded'},role,'source-file.txt','page 7')])
    f=r.known_facts[0]
    assert f.source_file=='source-file.txt' and f.source_locator=='page 7'
    assert f.snippet=='grounded supporting excerpt'
    assert f.extraction_method=='cp009-test-fixture'
    assert f.artifact_type==role and f.source_role==role

@pytest.mark.parametrize('qid', QIDS)
def test_future_dated_operating_evidence_cannot_establish(qid):
    s=QUESTION_SPECS[qid]
    # Supply valid design facts, but all operating facts are dated in the future.
    cs=[]
    if s.design: cs.append(claim(s.topic,attrs(s.design),'POLICY','policy.txt'))
    if s.operating: cs.append(claim(s.topic,attrs(s.operating),'RECORD','future.csv', evidence_date='2999-01-01'))
    r=area(qid,cs)
    assert r.status != ESTABLISHED, (qid,r.status)
    assert any('future/invalid evidence date' in x for x in r.missing_facts), (qid,r.missing_facts)
