from datetime import date
from pathlib import Path
from ingestion import extract
from bcp_dr import extract_recovery_facts, reconcile_recovery
from evidence.pipeline import analyze_evidence_file

import pytest
_REPO=Path(__file__).resolve().parents[2]
PACK=next((p for p in (_REPO/'test_evidence'/'driftguard_soc2_test_pack'/'12_BCP_DR',
                       _REPO/'original_pack'/'driftguard_soc2_test_pack'/'12_BCP_DR') if p.is_dir()),
          _REPO/'test_evidence'/'driftguard_soc2_test_pack'/'12_BCP_DR')
pytestmark=pytest.mark.skipif(not PACK.is_dir(),reason='CP011 BCP/DR test pack not found under test_evidence/ or original_pack/')

def docs():
    return [extract(p.name,p.read_bytes()) for p in sorted(PACK.iterdir())]

def test_amma_pack_extracts_grounded_recovery_facts():
    facts=extract_recovery_facts(docs())
    keys={f.key for f in facts}
    assert {'bcp_plan_exists','dr_plan_or_test_exists','target_rto_minutes','target_rpo_minutes','dr_test_date','actual_recovery_minutes','observed_data_loss_minutes','test_outcome'} <= keys
    assert all(f.provenance.filename and f.provenance.locator and f.provenance.excerpt for f in facts)

def test_plan_and_test_evidence_roles_remain_distinct():
    facts=extract_recovery_facts(docs())
    assert any(f.key=='target_rto_minutes' and f.evidence_role=='PLAN_OBJECTIVE' for f in facts)
    assert any(f.key=='actual_recovery_minutes' and f.evidence_role=='TEST_RESULT' for f in facts)

def test_reporting_rpo_miss_is_reconciled_with_provenance():
    a=reconcile_recovery(extract_recovery_facts(docs()),as_of=date(2026,9,30))
    miss=[i for i in a.issues if i.code=='OBJECTIVE_NOT_MET' and 'reporting' in i.detail]
    assert miss and 'RPO' in miss[0].detail
    assert len(miss[0].provenance)==2

def test_open_dr_corrective_action_is_surfaced_not_called_control_failure():
    a=reconcile_recovery(extract_recovery_facts(docs()),as_of=date(2026,9,30))
    issue=next(i for i in a.issues if i.code=='DR-REMEDIATION-OPEN')
    assert 'DR-118' in issue.detail and issue.state=='NEEDS_REVIEW'

def test_backup_repeated_system_different_runs_not_duplicate():
    p=PACK/'Backup_Job_Report.csv'
    r=analyze_evidence_file(p.name,p.read_bytes(),as_of=date(2026,9,30))
    assert r.evidence_type=='BACKUP_JOB_REPORT'
    assert not any(c.check_id=='KEY-DUPLICATE' for c in r.checks)
    assert any(c.check_id=='BACKUP-RUN-FAILED' for c in r.checks)
    assert any(c.check_id=='RESTORE-NOT-VALIDATED' for c in r.checks)

def test_actual_duplicate_backup_run_is_detected():
    raw=b'System,Backup Type,Scheduled,Completed,Result,Restore Tested\nprod-db,Daily,2026-09-30 02:00,2026-09-30 02:12,Success,Yes\nprod-db,Daily,2026-09-30 02:00,2026-09-30 02:12,Success,Yes\n'
    r=analyze_evidence_file('backup.csv',raw,as_of=date(2026,9,30))
    assert any(c.check_id=='KEY-DUPLICATE' for c in r.checks)

def test_backup_success_does_not_prove_restore():
    p=PACK/'Backup_Job_Report.csv'
    r=analyze_evidence_file(p.name,p.read_bytes(),as_of=date(2026,9,30))
    assert any(c.check_id=='RESTORE-NOT-VALIDATED' for c in r.checks)

def test_program_metadata_and_owner_conflict_are_grounded():
    a=extract('BCP.txt',b'Business Continuity Plan\nPlan Owner: Alice\nApproved By: CAB\nReview Date: 2026-01-05\nCritical Services: payments\nRecovery Location: eu-west-2\n')
    b=extract('DR.txt',b'Disaster Recovery Plan\nPlan Owner: Bob\nCritical Services: payments\n')
    facts=extract_recovery_facts([a,b])
    assert {'plan_owner','approval','review_date','critical_services','recovery_location'} <= {f.key for f in facts}
    r=reconcile_recovery(facts,as_of=date(2026,9,30))
    assert any(i.code=='OWNERSHIP-INCONSISTENT' and i.state=='CONFLICT' for i in r.issues)

def test_plan_test_objective_mismatch_and_scope_mismatch():
    plan=extract('DR_plan.txt',b'Disaster Recovery Plan\nPayments: RTO 4 hours, RPO 1 hour.\n')
    test=extract('DR_test.txt',b'Disaster Recovery Test Results\nTarget RTO\nActual Recovery\nTarget RPO\nObserved Data Loss\nResult\nPayments\n5h\n3h\n1h\n30m\nMet\nWarehouse\n2h\n1h\n1h\n30m\nMet\nExercise date: 2026-09-01.')
    r=reconcile_recovery(extract_recovery_facts([plan,test]),as_of=date(2026,9,30))
    assert any(i.code=='OBJECTIVE-MISMATCH' and i.state=='CONFLICT' for i in r.issues)
    assert any(i.code=='SYSTEM-SCOPE-MISMATCH' for i in r.issues)

def test_backup_facts_include_runs_and_restore_rows():
    p=PACK/'Backup_Job_Report.csv'; r=analyze_evidence_file(p.name,p.read_bytes(),as_of=date(2026,9,30))
    runs=r.fact('backup_runs').value
    assert len(runs)==3 and runs[0]['system']=='prod-db' and runs[0]['backup_type']=='Daily'
    assert r.fact('restore_validated_rows').value==(2,)

def test_document_assessment_carries_recovery_intelligence():
    from assessment import MvpKnowledge
    from documents import DocumentAnalyzer
    a=DocumentAnalyzer(MvpKnowledge()).analyze('amma',docs(),[],True)
    assert a.recovery is not None
    assert any(i.code=='OBJECTIVE_NOT_MET' for i in a.recovery.issues)

def test_extended_bcp_dr_fields_are_supported_without_invention():
    d=extract('Recovery.txt',b'''Disaster Recovery Plan\nPlan Owner: Alice\nBackup Retention: 35 days\nImmutable backup stored in secondary region.\nTest Scenario: primary region outage\nRemediation Owner: Carol\nDue Date: 2026-10-15\nRestore Test Result: Passed\n''')
    facts=extract_recovery_facts([d]); keys={f.key for f in facts}
    assert {'retention','offsite_isolated_backup','test_scenario','remediation_owner','remediation_due_date','restore_result'} <= keys
    assert all(f.provenance.excerpt for f in facts)

def test_daily_backup_staleness_uses_stated_cadence():
    raw=b'System,Backup Type,Scheduled,Completed,Result,Restore Tested\nprod-db,Daily,2026-09-01 02:00,2026-09-01 02:12,Success,Yes\n'
    r=analyze_evidence_file('backup.csv',raw,as_of=date(2026,9,30))
    assert any(c.check_id=='BACKUP-RUN-STALE' for c in r.checks)
