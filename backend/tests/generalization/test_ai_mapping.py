import pytest
from driftguard_platform.ai import AIResult, AIRequest, AIOperation, registry
from evidence.tabular import read_tabular
from evidence.structured_registry import recognize
from evidence.ai_mapping import infer_with_ai, build_request_text, MappingStore, AI_SIGNAL, CONFIRMED_SIGNAL

CSV = ('x.csv', b'Job Label,Kickoff,Disposition\napi,2026-10-01,Successful\ndb,2026-10-02,Failed\n')
GOOD = {'role': 'BACKUP_JOB_REPORT', 'map': {'system': 'job label', 'scheduled': 'kickoff', 'result': 'disposition'}}


class Fake:
    name = 'fake'
    def __init__(self, data, confidence=0.93): self.data, self.confidence, self.calls = data, confidence, 0
    def execute(self, request):
        self.calls += 1
        return AIResult(request.operation, self.data, 'fake', 'm', request.source_ids, self.confidence)


def book(): return read_tabular(*CSV)


def test_ai_disabled_by_default_stays_unclassified():
    assert recognize(book()) is None and infer_with_ai(book()) is None


def test_valid_mapping_accepted_and_flagged_unconfirmed():
    inf = infer_with_ai(book(), Fake(GOOD))
    assert inf.role == 'BACKUP_JOB_REPORT' and AI_SIGNAL in inf.signals


def test_recognize_uses_ai_through_existing_pipeline(monkeypatch):
    registry.register('fake', lambda **_: Fake(GOOD)); monkeypatch.setenv('DRIFTGUARD_AI_PROVIDER', 'fake')
    spec, sheet = recognize(book())
    assert spec.kind == 'BACKUP_JOB_REPORT' and 'system' in sheet.headers and AI_SIGNAL in spec.classification_signals


def test_invented_header_rejected():
    bad = {**GOOD, 'map': {**GOOD['map'], 'result': 'made up column'}}
    assert infer_with_ai(book(), Fake(bad)) is None


def test_unknown_role_or_field_rejected():
    assert infer_with_ai(book(), Fake({**GOOD, 'role': 'FIREWALL_RULES'})) is None
    assert infer_with_ai(book(), Fake({**GOOD, 'map': {'nonsense': 'kickoff'}})) is None


def test_missing_required_group_rejected():
    assert infer_with_ai(book(), Fake({**GOOD, 'map': {'system': 'job label'}})) is None


def test_low_confidence_and_null_role_rejected():
    assert infer_with_ai(book(), Fake(GOOD, confidence=0.5)) is None
    assert infer_with_ai(book(), Fake({'role': None})) is None


def test_prohibited_verdict_rejected():
    assert infer_with_ai(book(), Fake({**GOOD, 'note': 'COMPLIANT'})) is None


def test_confirmed_mapping_reused_without_ai(tmp_path):
    store = MappingStore(tmp_path / 'm.json')
    assert store.confirm(book().sheets[0], GOOD['role'], GOOD['map'])
    fake = Fake({'role': None}); inf = infer_with_ai(book(), fake, store)
    assert inf.role == 'BACKUP_JOB_REPORT' and CONFIRMED_SIGNAL in inf.signals and fake.calls == 0


def test_invalid_mapping_not_stored(tmp_path):
    assert not MappingStore(tmp_path / 'm.json').confirm(book().sheets[0], GOOD['role'], {'system': 'nope'})


def test_request_is_compact_and_grounded():
    text, ids = build_request_text(book().sheets[0])
    assert text.splitlines()[0] == 'H: job label | kickoff | disposition' and len(text.splitlines()) == 3
    assert all(i.startswith('x.csv|') for i in ids) and ids


def test_classify_requires_source_ids():
    from driftguard_platform.ai import validate_result, AIValidationError
    with pytest.raises(AIValidationError):
        validate_result(AIResult(AIOperation.CLASSIFY, {'role': None}, 'f', 'm', (), .9))


def test_unconfirmed_ai_result_needs_review_with_note(monkeypatch):
    from evidence.pipeline import analyze_evidence_file
    registry.register('fake', lambda **_: Fake(GOOD)); monkeypatch.setenv('DRIFTGUARD_AI_PROVIDER', 'fake')
    r = analyze_evidence_file(*CSV)
    assert r.evidence_type == 'BACKUP_JOB_REPORT' and r.needs_review
    assert any('suggested by AI' in n for n in r.notes) and AI_SIGNAL in r.matched_signals


def _client(): 
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def _post(client, mapping, **extra):
    import json
    return client.post('/api/v1/evidence/mapping/confirm', files={'files': CSV},
                       data={'role': 'BACKUP_JOB_REPORT', 'mapping': json.dumps(mapping), **extra})


def test_confirm_endpoint_requires_store(monkeypatch):
    monkeypatch.delenv('DRIFTGUARD_MAPPING_STORE', raising=False)
    assert _post(_client(), GOOD['map']).status_code == 409


def test_confirm_endpoint_stores_then_reused_without_ai(monkeypatch, tmp_path):
    monkeypatch.setenv('DRIFTGUARD_MAPPING_STORE', str(tmp_path / 'm.json'))
    c = _client(); r = _post(c, GOOD['map'], customer='acme')
    assert r.status_code == 200 and r.json()['confirmed']
    fake = Fake({'role': None})
    inf = infer_with_ai(book(), fake, MappingStore(tmp_path / 'm.json', 'acme'))
    assert CONFIRMED_SIGNAL in inf.signals and fake.calls == 0
    assert infer_with_ai(book(), Fake({'role': None}), MappingStore(tmp_path / 'm.json', 'other')) is None


def test_confirm_endpoint_rejects_bad_mapping(monkeypatch, tmp_path):
    monkeypatch.setenv('DRIFTGUARD_MAPPING_STORE', str(tmp_path / 'm.json'))
    assert _post(_client(), {'system': 'nope'}).status_code == 422
    assert not (tmp_path / 'm.json').exists()


def test_eval_cases_are_valid_and_unknown_to_synonym_table():
    """Guards the accuracy dataset: expected answers pass validation; weak cases stay unclassified."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from ai_mapping_eval import CASES
    from evidence.schema_generalization import infer_workbook
    from evidence.ai_mapping import _validate
    for text, role, expected in CASES:
        b = read_tabular('e.csv', text.encode())
        if role is None:
            assert infer_workbook(b) is None; continue
        assert _validate(b.sheets[0], {'role': role, 'map': expected, 'confidence': 1}) is not None, text


def test_openrouter_registered_and_needs_key(monkeypatch):
    from driftguard_platform.ai import AIUnavailable
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    p = registry.create('openrouter')
    assert p.name == 'openrouter'
    with pytest.raises(AIUnavailable): p.execute(AIRequest(AIOperation.CLASSIFY, 'x', {}, ('a',)))


def test_json_parse_tolerates_code_fence():
    from driftguard_platform.ai import _json_from_text
    assert _json_from_text('```json\n{"role": null}\n```') == {'role': None}
    assert _json_from_text('{"role": null}') == {'role': None}
