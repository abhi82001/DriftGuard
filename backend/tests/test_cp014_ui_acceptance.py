import asyncio, os, sys, json
from pathlib import Path
from urllib.parse import urlencode
SRC=Path(__file__).resolve().parent.parent/'src'; sys.path.insert(0,str(SRC))
os.environ['DRIFTGUARD_DEMO_MODE']='1'
import app as webapp

def call(method,path,form=None,body=None,ctype=None):
    if body is None:
        body=urlencode(form or {},doseq=True).encode() if form else b''
        ctype=ctype or ('application/x-www-form-urlencoded' if form else None)
    headers=[(b'host',b'test'),(b'content-length',str(len(body)).encode())]
    if ctype: headers.append((b'content-type',ctype.encode()))
    scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.3'},'http_version':'1.1','method':method,'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'','root_path':'','headers':headers,'client':('test',1),'server':('test',80)}
    sent=[]
    async def receive(): return {'type':'http.request','body':body,'more_body':False}
    async def send(m): sent.append(m)
    asyncio.run(webapp.app(scope,receive,send))
    start=next(m for m in sent if m['type']=='http.response.start')
    text=b''.join(m.get('body',b'') for m in sent if m['type']=='http.response.body').decode()
    loc=dict(start['headers']).get(b'location',b'').decode()
    return start['status'],text,loc,dict(start['headers'])

def multipart(files,vendor='Browser Vendor'):
    b='----DGBOUNDARY'; parts=[]
    parts += [f'--{b}\r\nContent-Disposition: form-data; name="vendor"\r\n\r\n{vendor}\r\n'.encode()]
    for name,data,typ in files:
        parts += [f'--{b}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\nContent-Type: {typ}\r\n\r\n'.encode()+data+b'\r\n']
    parts += [f'--{b}--\r\n'.encode()]
    return b''.join(parts),f'multipart/form-data; boundary={b}'

def make_assessment():
    body,ct=multipart([('mfa_policy.txt',b'Information Security Policy. MFA is required for all workforce access.','text/plain'),('backup.csv',b'system,frequency,date,result\nprod-db,Daily,2026-09-29,Success\n','text/csv')])
    st,_,loc,_=call('POST','/analyze',body=body,ctype=ct); assert st==303
    return loc.rsplit('/',1)[1]

def test_dashboard_separates_required_metrics_and_semantic_state():
    aid=make_assessment(); st,text,_,_=call('GET',f'/doc-results/{aid}')
    assert st==200
    for x in ['Files received','Files parsed','Structured artifacts validated','Narrative documents analyzed','Questions evaluated','Questions not evaluated','Established','Partial','Not established','Clarification','Conflict','SEMANTIC ANALYSIS UNAVAILABLE']:
        assert x in text,x

def test_question_detail_exposes_trace_and_rejection_policy():
    aid=make_assessment(); _,text,_,_=call('GET',f'/doc-results/{aid}')
    for x in ['Why:','Evidence used:','Still unknown','Evidence rejected:','Contradictions:','Source provenance:','Supporting excerpt:']:
        assert x in text,x

def test_evidence_qa_explains_validation_scope():
    aid=make_assessment(); _,text,_,_=call('GET',f'/evidence-report/{aid}')
    for x in ['Recognized artifact type:','Validator used:','Checks performed:','Checks not performed / limitations:','Facts extracted:','Exceptions:','classification identifies the artifact schema']:
        assert x in text,x

def test_export_is_grounded_json_report():
    aid=make_assessment(); st,text,_,headers=call('GET',f'/export/{aid}')
    assert st==200 and b'application/json' in headers[b'content-type']
    data=json.loads(text); assert data['assessment_id']==aid and len(data['questions'])==29
    assert 'compliance conclusion' in data['disclaimer']

def test_invalid_and_malformed_uploads_fail_closed():
    body,ct=multipart([('evil.exe',b'MZ','application/octet-stream')]); st,_,_,_=call('POST','/analyze',body=body,ctype=ct); assert st==415
    body,ct=multipart([('fake.pdf',b'not pdf','application/pdf')]); st,_,_,_=call('POST','/analyze',body=body,ctype=ct); assert st==415

def test_oversized_upload_is_rejected():
    from ingestion import MAX_BYTES
    body,ct=multipart([('too-big.txt',b'x'*(MAX_BYTES+1),'text/plain')]); st,_,_,_=call('POST','/analyze',body=body,ctype=ct)
    assert st==413

def test_provider_unavailable_is_explicit_not_silent_semantic_fallback():
    aid=make_assessment(); _,text,_,_=call('GET',f'/doc-results/{aid}')
    assert 'SEMANTIC ANALYSIS UNAVAILABLE' in text
    assert 'DETERMINISTIC ONLY' in text
    assert 'SEMANTIC ANALYSIS ACTIVE' not in text
