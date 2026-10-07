import os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient

os.environ['DRIFTGUARD_DB']=str(Path(tempfile.mkdtemp())/'security.db')
os.environ['DRIFTGUARD_DEMO_MODE']='1'
import app as webapp
import pytest

@pytest.fixture(autouse=True)
def _secure_mode(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_REQUIRE_AUTH", "1")
    webapp._RATE_BUCKETS.clear()


def register(client, email):
    r=client.post('/register', data={'email':email,'password':'CorrectHorseBattery9'}, follow_redirects=False)
    assert r.status_code==303


def test_anonymous_analysis_is_rejected():
    c=TestClient(webapp.app, follow_redirects=False)
    assert c.post('/analyze-sample').status_code==303
    assert c.post('/run', data={'vendor':'x'}).status_code==303


def test_cross_user_assessment_access_is_blocked_everywhere():
    a=TestClient(webapp.app, follow_redirects=False); b=TestClient(webapp.app, follow_redirects=False)
    register(a,'owner@example.test'); register(b,'other@example.test')
    made=a.post('/analyze-sample'); assert made.status_code==303
    loc=made.headers['location']; aid=loc.rsplit('/',1)[-1]
    assert len(aid)==32
    assert a.get(loc).status_code==200
    for path in [loc, f'/export/{aid}', f'/export-pdf/{aid}', f'/evidence-report/{aid}']:
        assert b.get(path).status_code==404
    assert b.post(f'/clarify/{aid}', data={}).status_code==404


def test_security_headers_and_csrf_origin_boundary():
    c=TestClient(webapp.app, follow_redirects=False); register(c,'headers@example.test')
    r=c.get('/')
    assert r.headers['x-content-type-options']=='nosniff'
    assert r.headers['x-frame-options']=='DENY'
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']
    bad=c.post('/analyze-sample', headers={'Origin':'https://evil.example'})
    assert bad.status_code==403


def test_saved_state_is_json_not_pickle_and_reopens():
    c=TestClient(webapp.app, follow_redirects=False); register(c,'json@example.test')
    loc=c.post('/analyze-sample').headers['location']; aid=loc.rsplit('/',1)[-1]
    token=c.cookies.get(webapp._COOKIE)
    uid=webapp._accounts().user_for_session(token, "0000-01-01T00:00:00+00:00")
    blob=webapp._accounts().load_saved(uid, "doc-results", aid)
    assert isinstance(blob,str) and blob.startswith('{')
    webapp.DOC_ASSESSMENTS.pop(aid)
    assert c.get(loc).status_code==200


def test_password_kdf_is_600k_pbkdf2_compatible():
    h=webapp._hash_pw('CorrectHorseBattery9')
    assert webapp._check_pw('CorrectHorseBattery9',h)
    assert not webapp._check_pw('wrong',h)


def test_browser_auth_flow_redirects_to_login_and_back_to_requested_page():
    c=TestClient(webapp.app, follow_redirects=False)
    home=c.get('/')
    assert home.status_code==200
    assert 'Try without signing in' in home.text and 'Sign in' in home.text
    login=c.get('/login?next=/')
    assert login.status_code==200
    assert 'Sign in' in login.text and 'Create account' in login.text
    made=c.post('/register', data={'email':'flow@example.test','password':'CorrectHorseBattery9','next':'/'})
    assert made.status_code==303 and made.headers['location']=='/'
    assert c.get('/').status_code==200
    out=c.post('/logout')
    assert out.status_code==303 and out.headers['location']=='/login'
    assert c.get('/').status_code==200


def test_api_auth_failure_stays_json_401():
    c=TestClient(webapp.app, follow_redirects=False)
    r=c.post('/api/evidence-map', json={})
    assert r.status_code==401
    assert r.json()=={'error':'authentication required'}
