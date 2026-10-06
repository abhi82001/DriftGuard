from __future__ import annotations
import json, os, subprocess, sys
from datetime import date
from pathlib import Path
import pytest
from fastapi import HTTPException
from ingestion import extract, IngestionError, MAX_BYTES
from upload_security import validate_file
from evidence.model import STALE, EVIDENCE_STATES, aggregate_state
from evidence.temporal_review import assess_freshness
from semantic_extraction import extract_document
from ingestion import Document, Chunk

ROOT=Path(__file__).resolve().parents[3]
SC=ROOT/'backend/tests/fixtures/cp0171_scenarios'

def run_pack(name):
    out=ROOT/'artifacts'/f'cp0171_{name}.json'
    env=os.environ.copy(); env['PYTHONPATH']=str(ROOT/'backend/src')
    p=subprocess.run([sys.executable,str(ROOT/'run_pack.py'),str(SC/name),'--assessment-date','2026-10-06','--output',str(out)],cwd=ROOT,env=env,capture_output=True,text=True)
    assert p.returncode==0, p.stdout+p.stderr
    return json.loads(out.read_text())

def test_explicit_stale_evidence_state_exists_without_becoming_control_failure():
    assert STALE in EVIDENCE_STATES
    assert aggregate_state((STALE,))==STALE
    f=assess_freshness('2023-06-30','quarterly',as_of=date(2026,10,6))
    assert f['state']==STALE and 'STALE EVIDENCE' in f['reason']

def test_runner_conflict_end_to_end():
    r=run_pack('conflict')
    o=[x for x in r['cross_artifact_findings'] if x['state']=='CONFLICT']
    assert o and len(o[0]['provenance'])==2

def test_runner_stale_end_to_end():
    r=run_pack('stale')
    q=next(x for x in r['questionnaire_results'] if x['question_id']=='QN-ACCESS-001-Q03')
    assert q['status']=='PARTIALLY_ESTABLISHED'
    assert 'STALE EVIDENCE' in q['reason']
    assert q['provenance']

def test_runner_missing_end_to_end_is_not_failure_language():
    r=run_pack('missing')
    assert r['questionnaire_counts']['missing_evidence']>0
    missing=[x for x in r['questionnaire_results'] if x['status']=='NOT_ESTABLISHED']
    assert missing
    assert all('not a control failure' in x['reason'].lower() for x in missing)

def test_runner_ambiguous_end_to_end():
    r=run_pack('ambiguous')
    e=next(x for x in r['evidence_results'] if x['filename']=='unknown.csv')
    assert e['role']=='UNCLASSIFIED' and e['needs_review']

def test_runner_objective_not_met_end_to_end_with_two_sources():
    r=run_pack('dr_miss')
    x=next(x for x in r['recovery_findings'] if x['code']=='OBJECTIVE_NOT_MET')
    assert x['state']=='NEEDS_REVIEW'
    assert len(x['provenance'])==2
    assert {p['filename'] for p in x['provenance']}=={'plan.txt','test.txt'}

def test_empty_non_utf8_and_oversize_upload_behavior():
    with pytest.raises(HTTPException) as e: validate_file('empty.txt',b'')
    assert e.value.status_code==400
    # Plain text is decoded safely as untrusted data; invalid bytes are replaced, not executed.
    d=extract('odd.txt',b'hello\xffworld')
    assert '\ufffd' in d.text
    with pytest.raises(HTTPException) as e: validate_file('huge.txt',b'x'*(MAX_BYTES+1))
    assert e.value.status_code==413

class BoomProvider:
    def extract(self, request): raise TimeoutError('provider timed out')

def test_semantic_timeout_isolated_and_not_silent_pass():
    d=Document('p.txt','policy',(Chunk('p.txt','line 1','MFA is required.'),))
    facts,rejections=extract_document(d,BoomProvider(),'POLICY')
    assert facts==[]
    assert rejections and 'provider error: TimeoutError' in rejections[0].reason
