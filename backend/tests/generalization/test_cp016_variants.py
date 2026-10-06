import pytest
from datetime import date
from ingestion import extract_many
from narrative_intelligence import extract_narrative_facts
from bcp_dr import extract_recovery_facts,reconcile_recovery
from evidence.tabular import read_tabular
from evidence.structured_registry import recognize
from evidence.graph import graph_from_files
from evidence.temporal_review import assess_freshness

def C(n,s):return(n,s.encode())
def K(s):
 b=read_tabular('v.csv',s.encode());r=recognize(b);return r[0].kind if r else None
@pytest.mark.parametrize('text',["Security Policy. Operators must use another authentication factor.","Security Standard. An additional verification factor is required for admins.","Security Policy. Administrative access requires a second factor."])
def test_mfa_requirement_variants(text):
 d,_=extract_many([('p.txt',text.encode())]);assert any(f.concept=='mfa' and f.attribute=='requirement' for f in extract_narrative_facts(d))
@pytest.mark.parametrize('d',["2023-01-15","15-Jun-2023","2023/09/01"])
def test_stale_review_variants(d):assert assess_freshness(d,'quarterly',as_of=date(2026,10,6))['state']=='STALE'
@pytest.mark.parametrize('hr,idp',[
 ('Staff Login,Worker State,Last Day\nAUser@corp.com,Terminated,2026-01-01\n','Principal,Account State,Other\nauser,Active,x\n'),
 ('Worker Login,Employment Status,Termination Date\nBUSER,Terminated,2026-02-01\n','User,Status,Other\nbuser@corp.com,Enabled,x\n'),
 ('Employee,HR Status,End Date\nCUser,Terminated,2026-03-01\n','Login,Account Status,Other\ncuser,Active,x\n')])
def test_hr_idp_variants(hr,idp):assert any(o.state=='CONFLICT' for o in graph_from_files([C('h.csv',hr),C('i.csv',idp)]).observations)
@pytest.mark.parametrize('asset,edr',[
 ('Machine Name,Protection Required,Other\na1.corp.com,Yes,x\n','Host Name,Agent Installed,Other\na1,No,x\n'),
 ('Server,EDR Expected,Other\nb2,Required,x\n','Device,Endpoint Installed,Other\nb2,False,x\n'),
 ('Computer,EDR Required,Other\nc3,Yes,x\n','Asset,EDR Enabled,Other\nc3,No,x\n')])
def test_edr_variants(asset,edr):assert any(o.code=='EDR-COVERAGE-GAP' for o in graph_from_files([C('a.csv',asset),C('e.csv',edr)]).observations)
@pytest.mark.parametrize('v,t',[ 
 ('Vulnerability ID,Risk Severity,Ticket ID,Current State\nCVE-2026-1111,Critical,T1,Open\n','Case ID,Current State,CVE\nT1,Closed,CVE-2026-1111\n'),
 ('Finding,Severity,Remediation Ticket,Status\nCVE-2026-2222,High,T2,Active\n','Ticket ID,Status,CVE\nT2,Resolved,CVE-2026-2222\n'),
 ('CVE ID,Criticality,Case,State\nCVE-2026-3333,Critical,T3,Unresolved\n','Change,Outcome,CVE\nT3,Completed,CVE-2026-3333\n')])
def test_vuln_closure_variants(v,t):assert any(o.code=='CLOSURE-CONFLICT' for o in graph_from_files([C('v.csv',v),C('t.csv',t)]).observations)
@pytest.mark.parametrize('plan,test',[('RTO: 4 hours.','Actual recovery completed in 5.5 hours.'),('Recovery time objective = 240 minutes.','Measured restoration took 330 min.'),('RTO target 4h.','Observed recovery time: 330 minutes.')])
def test_rto_variants(plan,test):
 d,_=extract_many([('plan.txt',('Disaster recovery plan. '+plan).encode()),('test.txt',('Recovery test results. '+test).encode())]);assert any(i.code=='OBJECTIVE_NOT_MET' for i in reconcile_recovery(extract_recovery_facts(d)).issues)
@pytest.mark.parametrize('text',["Workload,Run Time,Outcome\napi,2026-10-01,Successful\napi,2026-10-02,Successful\n","System,Backup Date,Backup Status\ndb,2026-09-01,Success\ndb,2026-09-02,Success\n","Service,Scheduled Time,Result\nweb,2026-08-01,Successful\nweb,2026-08-02,Successful\n"])
def test_backup_schema_variants(text):assert K(text)=='BACKUP_JOB_REPORT'
