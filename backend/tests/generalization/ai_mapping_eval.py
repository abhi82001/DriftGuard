"""Accuracy harness for AI column mapping. Not collected by pytest (no test_ prefix).

Run against a real provider:
    DRIFTGUARD_AI_PROVIDER=openai OPENAI_API_KEY=... python backend/tests/generalization/ai_mapping_eval.py
Each case is a layout the synonym table does NOT recognise, with the correct mapping.
Headers are normalized (lowercase), as the reader produces them.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from evidence.tabular import read_tabular
from evidence.schema_generalization import infer_workbook
from evidence.ai_mapping import infer_with_ai, MappingStore

# (csv text, expected role, expected {field: header}); None role = must stay unclassified
CASES = [
 ('Job Label,Kickoff,Disposition\napi,2026-10-01,Successful\ndb,2026-10-02,Failed\n',
  'BACKUP_JOB_REPORT', {'system': 'job label', 'scheduled': 'kickoff', 'result': 'disposition'}),
 ('Dataset,Snapshot Began,Snapshot Verdict,Notes\nerp,2026-09-30 22:00,Success,ok\ncrm,2026-09-30 23:00,Failure,disk\n',
  'BACKUP_JOB_REPORT', {'system': 'dataset', 'scheduled': 'snapshot began', 'result': 'snapshot verdict'}),
 ('Colleague,Contract State,Departure\njsmith,Active,\nakhan,Ended,2026-08-15\n',
  'HR_ACTIVE_WORKER_ROSTER', {'employee': 'colleague', 'employment status': 'contract state'}),
 ('Badge Holder,Hire Standing,Exit Date\nt.doe,Terminated,2026-07-01\nm.lee,Employed,\n',
  'HR_ACTIVE_WORKER_ROSTER', {'employee': 'badge holder', 'employment status': 'hire standing'}),
 ('Directory Entry,Enabled State,Department\njsmith,Enabled,IT\nakhan,Disabled,HR\n',
  'IDENTITY_PROVIDER_EXPORT', {'user id': 'directory entry', 'status': 'enabled state'}),
 ('Box,Sensor Present,Owner\nsrv01,Yes,ops\nsrv02,No,ops\n',
  'ENDPOINT_PROTECTION_COVERAGE', {'hostname': 'box', 'edr installed': 'sensor present'}),
 ('Weakness,Impact Level,Box\nCVE-2026-1111,Critical,srv01\nCVE-2026-2222,High,srv02\n',
  'VULNERABILITY_REMEDIATION', {'finding': 'weakness', 'severity': 'impact level'}),
 ('Request,Progress,Approver\nCHG-100,Closed,mlee\nCHG-101,Open,pjones\n',
  'PRODUCTION_CHANGE_TICKETS', {'change': 'request', 'status': 'progress'}),
 ('Name,Sign-off By,Action Taken,Signed On\njsmith,mlee,Retain,2026-03-02\nakhan,mlee,Revoke,2026-03-02\n',
  'USER_ACCESS_REVIEW', {'employee': 'name', 'reviewer': 'sign-off by', 'reviewer decision': 'action taken', 'review date': 'signed on'}),
 ('Thing,Note,Value\na,b,c\n', None, {}),                       # too weak: must not be guessed
 ('Fruit,Colour,Weight\napple,red,100\npear,green,120\n', None, {}),  # unrelated data
]


def preflight():
    """One visible call so a provider error or a rejected answer is not hidden behind 'None'."""
    from driftguard_platform.ai import AIOperation, AIRequest, registry, validate_result
    from evidence.ai_mapping import INSTRUCTIONS, build_request_text, _validate
    book = read_tabular('eval.csv', CASES[0][0].encode()); sheet = book.sheets[0]
    text, ids = build_request_text(sheet)
    try:
        res = validate_result(registry.create().execute(AIRequest(AIOperation.CLASSIFY, text, {'instructions': INSTRUCTIONS}, ids)))
    except Exception as exc:
        print(f'PREFLIGHT ERROR: {type(exc).__name__}: {exc}'); return False
    print('PREFLIGHT raw answer:', dict(res.data), 'confidence:', res.confidence)
    ok = _validate(sheet, {**dict(res.data), 'confidence': res.confidence})
    print('PREFLIGHT validation:', 'accepted' if ok else 'REJECTED by validator'); return True


def score():
    right = wrong = skipped = 0
    for text, role, expected in CASES:
        book = read_tabular('eval.csv', text.encode())
        if infer_workbook(book) is not None:
            print('SKIP (deterministic already handles):', text.splitlines()[0]); skipped += 1; continue
        inf = infer_with_ai(book, store=MappingStore(None))
        got = (inf.role, {k: v for k, v in inf.mapping.items() if k in expected}) if inf else (None, {})
        ok = got == (role, expected) if role else inf is None
        right += ok; wrong += not ok
        print('OK  ' if ok else 'FAIL', text.splitlines()[0], '->', inf.role if inf else None)
    print(f'\ncorrect={right} wrong={wrong} skipped={skipped} of {len(CASES)}')
    return wrong == 0


if __name__ == '__main__':
    if os.getenv('DRIFTGUARD_AI_PROVIDER', 'disabled') == 'disabled':
        sys.exit('Set DRIFTGUARD_AI_PROVIDER (e.g. openai) to measure accuracy; AI is disabled.')
    if not preflight():
        sys.exit('Fix the provider error above before scoring.')
    sys.exit(0 if score() else 1)
