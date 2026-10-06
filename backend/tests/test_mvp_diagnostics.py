"""Adversarial regression based on amma assessment 8c807a60ce80.
The risk row is transcribed from the user-supplied report, not the original CSV bytes.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ingestion import extract
from assessment import MvpKnowledge
from documents import DocumentAnalyzer, NOT_ESTABLISHED
from evidence.pipeline import analyze_evidence_file
from app import DOC_ASSESSMENTS, doc_results, evidence_report

RISK = (b'Risk ID,Risk,Rating,Owner,Treatment,Residual,Status,Review Date\n'
        b'R-001,Unauthorized production access,High,CISO,MFA + quarterly access review,Medium,Open,2026-08-15\n')

def test_risk_register_diagnostics_and_no_false_positive():
    doc = extract('Risk_Register.csv', RISK)
    structured = analyze_evidence_file('Risk_Register.csv', RISK)
    assert structured.evidence_type == 'UNCLASSIFIED'
    assert any('EQA-UNSUPPORTED-TYPE' in note for note in structured.notes)
    a = DocumentAnalyzer(MvpKnowledge()).analyze('amma', [doc], [], demo=False, evidence=[structured])
    assert a.claims == []  # incidental MFA/review text in risk treatment is not a claim
    assert a.counts == dict(documents_analyzed=1, established=0, partially_established=0, missing_evidence=29, clarification_required=0, conflict=0, not_evaluated=0)
    for qid in ('QN-ACCESS-001-Q03', 'QN-ACCESS-001-Q04', 'QN-ACCESS-001-Q05'):
        result = next(x for x in a.areas if x.question_id == qid)
        assert result.status == NOT_ESTABLISHED
        assert not result.known_facts
    DOC_ASSESSMENTS[a.assessment_id] = a
    try:
        page = doc_results(a.assessment_id).body.decode()
        qa = evidence_report(a.assessment_id).body.decode()
        for code in ('ENGINE-LOCAL-001', 'COVERAGE-001', 'CLAIMS-001',
                     'EQA-UNSUPPORTED-TYPE'):
            assert code in page, code
        assert 'EQA-UNSUPPORTED-TYPE' in qa
        assert 'signal groups not found' not in qa
    finally:
        DOC_ASSESSMENTS.pop(a.assessment_id, None)


def test_risk_register_ui_separates_unsupported_from_missing():
    doc = extract('Risk_Register.csv', RISK)
    structured = analyze_evidence_file('Risk_Register.csv', RISK)
    a = DocumentAnalyzer(MvpKnowledge()).analyze('amma', [doc], [], demo=False, evidence=[structured])
    DOC_ASSESSMENTS[a.assessment_id] = a
    try:
        page = doc_results(a.assessment_id).body.decode()
        assert '29 of 29 question(s) have explicit claim-evaluation contracts' in page
        assert 'Not yet supported by this evaluation engine' not in page
        assert 'No supported fact found' in page
        assert 'Requirements with evaluation rules' in page
        assert 'Why did I get these results?' in page
        assert 'Files without structured validation' in page
        assert 'Missing evidence</div>' not in page
        assert 'Not evaluated at runtime' in page
    finally:
        DOC_ASSESSMENTS.pop(a.assessment_id, None)
