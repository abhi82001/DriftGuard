from evidence.graph import build_evidence_graph, norm_identifier, explain
from evidence.tabular import read_tabular

def art(kind,name,text):
    b=read_tabular(name,text.encode()); return kind,b,b.sheets[0]

def test_hostname_and_fqdn_normalize_but_no_fuzzy_guess():
    assert norm_identifier('WEB01.example.com','hostname')=='web01'
    assert norm_identifier('WEB-01','hostname')!='web01'

def test_asset_edr_coverage_and_provenance():
    a=art('ASSET_INVENTORY','cmdb.csv','Asset ID,Hostname,Environment,Criticality,EDR,Encryption\nA1,web01.example.com,prod,high,yes,yes\nA2,db01,prod,high,yes,yes\n')
    e=art('ENDPOINT_PROTECTION_COVERAGE','edr.csv','Asset,Class,Expected,EDR Installed,Last Seen,Status\nA1,server,yes,yes,2026-01-01,ok\n')
    g=build_evidence_graph([a,e])
    c=g.coverage['asset inventory ↔ endpoint protection']
    assert c=={'source':2,'matched':1,'unmatched':1,'percent':50.0}
    gap=next(x for x in g.observations if x.code=='COVERAGE-GAP')
    assert gap.identifiers==('a2',) and gap.provenance[0].filename=='cmdb.csv'
    assert explain(g,gap)['sources'][0]['locator']=='A3'

def test_data_deletion_exact_join_and_edge_has_both_sources():
    a=art('DATA_INVENTORY','data.csv','Dataset,Classification,System,Retention,Deletion Method,Owner\nCustomers,High,A,30d,Erase,Bob\n')
    d=art('DATA_DELETION_RECORD','del.csv','Request,Dataset,Requested,Completed,Method,Validator,Status\nR1,Customers,2026-01-01,2026-01-02,Erase,Bob,Completed\n')
    g=build_evidence_graph([a,d]); edge=g.edges[0]
    assert edge.edge_type=='CONFIRMS'
    assert {p.filename for p in edge.provenance}=={'data.csv','del.csv'}

def test_ambiguous_one_to_many_is_not_silently_collapsed():
    a=art('ASSET_INVENTORY','a.csv','Asset ID,Hostname,Environment,Criticality,EDR,Encryption\nA1,x,prod,high,yes,yes\n')
    e=art('ENDPOINT_PROTECTION_COVERAGE','e.csv','Asset,Class,Expected,EDR Installed,Last Seen,Status\nA1,server,yes,yes,2026-01-01,ok\nA1,server,yes,yes,2026-01-02,ok\n')
    g=build_evidence_graph([a,e])
    assert any(o.code=='AMBIGUOUS-IDENTIFIER' for o in g.observations)

def test_hostname_device_normalization_is_explicit_and_supported():
    a=art('ASSET_INVENTORY','a.csv','Asset ID,Hostname,Environment,Criticality,EDR,Encryption\nA1,x,prod,high,yes,yes\n')
    e=art('DISK_ENCRYPTION_REPORT','e.csv','Device,OS,Encryption,Recovery Key Escrowed,Last Check\nx,Linux,on,yes,2026-01-01\n')
    g=build_evidence_graph([a,e])
    assert g.coverage['asset inventory ↔ disk encryption']['matched']==1
    assert not g.observations

def test_hr_idp_exact_identifier_relationship():
    h=art('HR_ACTIVE_WORKER_ROSTER','hr.csv','Employee ID,Worker Type,Employment Status,Start Date\nE1,employee,active,2025-01-01\nE2,employee,active,2025-01-01\n')
    i=art('IDENTITY_PROVIDER_EXPORT','idp.csv','User ID,Type,Status,Privileged,MFA Enrolled\nE1,human,active,no,yes\n')
    g=build_evidence_graph([h,i])
    assert g.coverage['HR roster ↔ IdP identities']['unmatched']==1
    assert any(e.edge_type=='BELONGS_TO' for e in g.edges)

def test_edr_contradiction_is_conflict_not_silent_choice():
    a=art('ASSET_INVENTORY','a.csv','Asset ID,Hostname,Environment,Criticality,EDR,Encryption\nA1,x,prod,high,yes,yes\n')
    e=art('ENDPOINT_PROTECTION_COVERAGE','e.csv','Asset,Class,Expected,EDR Installed,Last Seen,Status\nA1,server,yes,no,2026-01-01,gap\n')
    g=build_evidence_graph([a,e])
    o=next(o for o in g.observations if o.code=='CROSS-ARTIFACT-CONFLICT')
    assert o.state=='CONFLICT' and len(o.provenance)==2

def test_termination_vs_active_idp_is_conflict():
    t=art('TERMINATION_REPORT','t.csv','Employee,Termination Effective,IAM Case,Current IAM Status\nE1,2026-01-01,T1,Disabled\n')
    i=art('IDENTITY_PROVIDER_EXPORT','i.csv','User ID,Type,Status,Privileged,MFA Enrolled\nE1,human,Active,no,yes\n')
    g=build_evidence_graph([t,i])
    assert any(o.state=='CONFLICT' for o in g.observations)
