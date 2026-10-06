"""Domain rules do not promote register metadata into control effectiveness."""
from evidence.pipeline import analyze_evidence_file

def check(csv_text, expected_type, issue):
    result=analyze_evidence_file('renamed.csv',csv_text.encode())
    assert result.evidence_type==expected_type
    assert issue in {c.check_id for c in result.checks}
    assert result.needs_review
    assert all(c.provenance for c in result.checks if c.check_id==issue)

def test_deletion_closure_requires_completion_date():
    check('Request,Dataset,Requested,Completed,Method,Validator,Status\nD-1,customer,2026-01-01,,erase,Alice,Completed\n','DATA_DELETION_RECORD','DELETION-CLOSURE-UNSUPPORTED')

def test_deletion_cannot_precede_request():
    check('Request,Dataset,Requested,Completed,Method,Validator,Status\nD-1,customer,2026-02-01,2026-01-01,erase,Alice,Completed\n','DATA_DELETION_RECORD','DELETION-DATE-ORDER')

def test_risk_score_order_needs_review_not_access_review():
    result=analyze_evidence_file('access_review.csv',b'Risk ID,Risk,Inherent,Treatment,Residual,Review Date,Owner,Status\nR-1,breach,Low,mitigation,High,2026-01-01,Jane,Open\n')
    assert result.evidence_type=='RISK_REGISTER'
    assert 'RISK-SCORE-REVIEW' in {c.check_id for c in result.checks}
    assert all('access_review' not in f.key for f in result.facts)

def test_firewall_allow_rule_without_expiry_is_not_silently_approved():
    check('Rule ID,Source,Destination,Port,Action,Expiry,Owner\nF-1,0.0.0.0/0,prod,22,Allow,,Jane\n','FIREWALL_RULE_EXPORT','RULE-EXPIRY-REVIEW')

def test_closed_vulnerability_requires_closure_date():
    check('Finding,Severity,Owner,Status,Due Date,Closed Date\nV-1,High,Jane,Closed,2026-01-01,\n','VULNERABILITY_REMEDIATION','VULN-CLOSURE-UNSUPPORTED')
