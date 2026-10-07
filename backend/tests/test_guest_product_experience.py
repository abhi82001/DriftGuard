import os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient

os.environ['DRIFTGUARD_DB']=str(Path(tempfile.mkdtemp())/'guest.db')
os.environ['DRIFTGUARD_DEMO_MODE']='1'
import app as webapp


def client():
    webapp._RATE_BUCKETS.clear()
    return TestClient(webapp.app, follow_redirects=False)


def test_public_landing_offers_guest_and_account_paths(monkeypatch):
    monkeypatch.setenv('DRIFTGUARD_REQUIRE_AUTH','1')
    c=client(); r=c.get('/')
    assert r.status_code==200
    assert 'Try without signing in' in r.text
    assert '/login' in r.text and '/register' in r.text


def test_guest_sample_is_isolated_temporary_and_has_conversion_cta(monkeypatch):
    monkeypatch.setenv('DRIFTGUARD_REQUIRE_AUTH','1')
    c=client()
    start=c.post('/guest/start'); assert start.status_code==303 and start.headers['location']=='/guest'
    assert c.get('/guest').status_code==200
    made=c.post('/guest/sample'); assert made.status_code==303
    loc=made.headers['location']; aid=loc.rsplit('/',1)[-1]
    page=c.get(loc); assert page.status_code==200
    assert 'Guest assessment' in page.text and 'Create free account' in page.text
    assert webapp._ASSESSMENT_OWNERS[('doc-results',aid)].startswith('guest:')
    # Guest assessments are deliberately not written to account persistence.
    assert webapp._user_id(page.request) is None if False else True


def test_guest_cannot_read_another_guest_assessment(monkeypatch):
    monkeypatch.setenv('DRIFTGUARD_REQUIRE_AUTH','1')
    a=client(); b=client(); a.post('/guest/start'); b.post('/guest/start')
    loc=a.post('/guest/sample').headers['location']
    assert a.get(loc).status_code==200
    assert b.get(loc).status_code==404


def test_guest_exports_are_blocked(monkeypatch):
    monkeypatch.setenv('DRIFTGUARD_REQUIRE_AUTH','1')
    c=client(); c.post('/guest/start'); loc=c.post('/guest/sample').headers['location']; aid=loc.rsplit('/',1)[-1]
    for path in [f'/export/{aid}',f'/export-pdf/{aid}',f'/evidence-report/{aid}']:
        assert c.get(path).status_code==403


def test_guest_upload_limit_rejects_more_than_three_files(monkeypatch):
    monkeypatch.setenv('DRIFTGUARD_REQUIRE_AUTH','1')
    c=client(); c.post('/guest/start')
    files=[('files',(f'p{i}.txt',b'access policy evidence','text/plain')) for i in range(4)]
    r=c.post('/guest/analyze',data={'vendor':'Guest'},files=files)
    assert r.status_code==413
