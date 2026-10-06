from datetime import date
from ingestion import extract_many
from evidence.tabular import read_tabular
from evidence.structured_registry import recognize
from evidence.graph import graph_from_files, norm_identifier
from evidence.temporal_review import assess_freshness
from narrative_intelligence import extract_narrative_facts
from bcp_dr import extract_recovery_facts,reconcile_recovery

def csv(name,text): return (name,text.encode())
def kind(f):
    b=read_tabular(*f); r=recognize(b); return r[0].kind if r else None

def test_unknown_hr_headers(): assert kind(csv('x.csv','Staff Login,Worker State,Last Day\nJDoe@corp.com,Terminated,2026-01-01\n'))=='HR_ACTIVE_WORKER_ROSTER'
def test_unknown_idp_headers(): assert kind(csv('x.csv','Principal,Account State,Other\nJDoe,Active,x\n'))=='IDENTITY_PROVIDER_EXPORT'
def test_unknown_edr_headers(): assert kind(csv('x.csv','Machine Name,Agent Installed,Other\nsrv01,No,x\n'))=='ENDPOINT_PROTECTION_COVERAGE'
def test_unknown_vuln_headers(): assert kind(csv('x.csv','Vulnerability ID,Risk Severity,Machine\nCVE-2026-1234,Critical,srv01\n'))=='VULNERABILITY_REMEDIATION'
def test_unknown_ticket_headers(): assert kind(csv('x.csv','Case ID,Current State,CVE\nT-1,Closed,CVE-2026-1234\n'))=='PRODUCTION_CHANGE_TICKETS'
def test_unknown_backup_headers(): assert kind(csv('x.csv','Workload,Run Time,Outcome\napi,2026-10-01,Successful\n'))=='BACKUP_JOB_REPORT'
def test_identity_normalization_case_and_domain(): assert norm_identifier(' JDoe@corp.com ','employee')=='jdoe'
def test_hostname_fqdn_safe(): assert norm_identifier('srv01.corp.com','hostname')=='srv01'
def test_hostname_punctuation_not_merged(): assert norm_identifier('srv-01','hostname')!=norm_identifier('srv01','hostname')
def test_hr_idp_conflict_has_two_provenance():
    fs=[csv('hr.csv','Staff Login,Worker State,Last Day\nJDoe@corp.com,Terminated,2026-01-01\n'),csv('idp.csv','Principal,Account State,Other\njdoe,Active,x\n')]
    g=graph_from_files(fs); o=next(x for x in g.observations if x.state=='CONFLICT'); assert len(o.provenance)==2

def _facts(text,name='policy.txt'):
    docs,errs=extract_many([(name,text.encode())]); assert not errs; return extract_narrative_facts(docs)
def test_mfa_additional_factor_requirement(): assert any(f.concept=='mfa' and f.attribute=='requirement' for f in _facts('Security Policy. Administrators are required to pass an additional verification factor.'))
def test_mfa_exception_qualifier(): assert any('EXCEPTION' in f.qualifiers for f in _facts('Security Policy. Service accounts are exempt from the additional authentication factor.'))
def test_mfa_planned_qualifier(): assert any('PLANNED_OR_FUTURE' in f.qualifiers for f in _facts('Security Policy. Hardware keys will be introduced next quarter for administrators.'))
def test_stale_quarterly(): assert assess_freshness('2023-06-30','quarterly',as_of=date(2026,10,6))['state']=='STALE'
def test_future_rejected(): assert assess_freshness('2027-01-01','annual',as_of=date(2026,10,6))['state']=='REJECTED'
def test_current_annual(): assert assess_freshness('2026-01-01','annual',as_of=date(2026,10,6))['state']=='CURRENT'
def test_rto_miss_hours_variant():
    docs,_=extract_many([('plan.txt',b'Disaster recovery plan. RTO: 4 hours.'),('test.txt',b'Recovery test results. Actual recovery completed in 5.5 hours.')]); a=reconcile_recovery(extract_recovery_facts(docs)); assert any(x.code=='OBJECTIVE_NOT_MET' for x in a.issues)
def test_rto_miss_minutes_variant():
    docs,_=extract_many([('a.txt',b'Disaster recovery standard. Recovery time objective = 240 minutes.'),('b.txt',b'Validation report. Measured restoration took 330 min.')]); a=reconcile_recovery(extract_recovery_facts(docs)); assert any(x.code=='OBJECTIVE_NOT_MET' for x in a.issues)
def test_rto_issue_has_both_provenance():
    docs,_=extract_many([('a.txt',b'Disaster recovery plan. RTO 4h.'),('b.txt',b'Test results. Observed recovery time: 330 minutes.')]); a=reconcile_recovery(extract_recovery_facts(docs)); o=next(x for x in a.issues if x.code=='OBJECTIVE_NOT_MET'); assert len(o.provenance)==2
def test_unclassified_weak_schema(): assert kind(csv('x.csv','Thing,Note,Value\na,b,c\n')) is None
def test_no_false_identity_merge(): assert norm_identifier('jdoe2','employee') != norm_identifier('jdoe','employee')
