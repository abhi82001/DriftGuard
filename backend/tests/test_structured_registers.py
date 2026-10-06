"""Regression against actual synthetic-pack schemas and adversarial counterexamples."""
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from evidence.pipeline import analyze_evidence_file
from evidence.tabular import read_tabular
from evidence.structured_registry import recognize, analyze_register, SCHEMAS


def test_every_schema_has_distinct_required_header_signature():
    signatures=[frozenset(x.required) for x in SCHEMAS]
    assert len(signatures)==len(set(signatures))


def test_risk_register_does_not_assert_access_review_completion():
    raw=b'Risk ID,Risk,Inherent,Owner,Treatment,Residual,Status,Review Date\nR-001,Unauthorized access,High,CISO,MFA + quarterly access review,Medium,Open,2026-08-15\n'
    result=analyze_evidence_file('renamed.csv',raw)
    assert result.evidence_type=='RISK_REGISTER'
    assert set(f.key for f in result.facts)=={'record_count','record_ids'}
    assert result.value('latest_review') is None
    assert result.value('mfa_enforced') is None
    assert 'structural data-quality' in result.notes[0]


def test_duplicate_and_future_date_are_explicit_not_dropped():
    raw=b'Risk ID,Risk,Inherent,Owner,Treatment,Residual,Status,Review Date\nR-001,One,High,A,X,Medium,Open,2026-10-07\nR-001,Two,High,B,Y,Medium,Open,not-a-date\n'
    w=read_tabular('anything.csv',raw)
    spec,sheet=recognize(w)
    result=analyze_register(w,spec,sheet,as_of=date(2026,9,30))
    assert result.value('record_count')==2
    assert {'KEY-DUPLICATE','DATE-FUTURE','DATE-INVALID'}.issubset({x.check_id for x in result.checks})
    assert result.needs_review


def test_unrelated_csv_remains_unclassified():
    assert analyze_evidence_file('risk_register.csv',b'foo,bar,baz\n1,2,3\n').evidence_type=='UNCLASSIFIED'
