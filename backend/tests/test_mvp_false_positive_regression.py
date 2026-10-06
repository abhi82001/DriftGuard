"""Regression: a risk register cannot masquerade as an access review."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ingestion import extract
from claims import DemoClaimExtractor
from documents import DocumentAnalyzer, ESTABLISHED, NOT_ESTABLISHED, PARTIAL
from assessment import MvpKnowledge

RISK = b'Risk ID,Risk,Rating,Owner,Treatment,Residual,Status,Review Date\nR-001,Unauthorized production access,High,CISO,MFA + quarterly access review,Medium,Open,2026-08-15\n'

def test_risk_register_never_creates_completed_access_review():
    doc = extract('Risk_Register.csv', RISK)
    claims = DemoClaimExtractor().extract([doc])
    assert not any(c.topic == 'access_review' and ('latest_review' in c.attributes or 'reviewed_populations' in c.attributes) for c in claims)
    a = DocumentAnalyzer(MvpKnowledge()).analyze('amma', [doc], [], demo=False)
    for qid in ('QN-ACCESS-001-Q03', 'QN-ACCESS-001-Q04', 'QN-ACCESS-001-Q05'):
        row = next(x for x in a.areas if x.question_id == qid)
        assert row.status == NOT_ESTABLISHED, (qid, row)
        assert not row.known_facts

def test_policy_plus_risk_register_cannot_upgrade_cadence_to_established():
    policy = extract('Information_Security_Policy.txt', b'User access reviews are required quarterly.')
    risk = extract('Risk_Register.csv', RISK)
    a = DocumentAnalyzer(MvpKnowledge()).analyze('amma', [policy, risk], [], demo=False)
    row = next(x for x in a.areas if x.question_id == 'QN-ACCESS-001-Q03')
    assert row.status == PARTIAL
    assert all(f.source_file != 'Risk_Register.csv' for f in row.known_facts)

def test_unrelated_dated_csv_not_promoted_to_operating_evidence():
    doc = extract('Data_Inventory.csv', b'Asset,Owner,Review Date,Status\nDatabase,CISO,2026-08-15,Open\n')
    assert all(c.evidence_nature not in ('OPERATING_EVIDENCE', 'CONFIGURATION', 'RECORD') for c in DemoClaimExtractor().extract([doc]))
