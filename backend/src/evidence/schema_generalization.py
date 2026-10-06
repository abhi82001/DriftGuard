"""CP016 conservative schema generalization for unfamiliar tabular evidence."""
from __future__ import annotations
import re
from dataclasses import dataclass
from .tabular import Sheet, Workbook, normalize

TOKENS={
 'employee id':('employee id','worker id','person id','staff id','emp id'),
 'employee':('employee','worker','person','staff','staff login','worker login','user name','username','login','identity','principal','email','account'),
 'user id':('user id','username','login','identity','principal','email','account','user'),
 'employment status':('employment status','worker status','worker state','employment state','hr status','terminated','termination status'),
 'status':('status','state','result','outcome','account status','current state'),
 'termination effective':('termination effective','termination date','terminated date','end date','last day'),
 'asset id':('asset id','device id','machine id','server id','computer id'),
 'hostname':('hostname','host name','host','server','machine','device','computer','asset name'),
 'asset':('asset','hostname','host name','host','server','machine','device','computer'),
 'edr':('edr required','endpoint required','protection required','edr expected','required'),
 'edr installed':('edr installed','endpoint installed','agent installed','protection installed','installed','edr enabled'),
 'finding':('finding','finding id','vulnerability','vulnerability id','cve','cve id'),
 'severity':('severity','risk severity','priority','criticality'),
 'ticket':('ticket','ticket id','case','case id','remediation ticket','change'),
 'change':('change','change id','ticket','ticket id','case','case id','remediation ticket'),
 'reviewer':('reviewer','reviewed by','approver','certifier'),
 'review date':('review date','reviewed date','reviewed on','certification date','last review'),
 'reviewer decision':('reviewer decision','decision','review result','certification result','outcome'),
 'system':('system','service','application','workload','asset','server'),
 'backup type':('backup type','backup kind','type'),
 'scheduled':('scheduled','scheduled time','run time','backup date','timestamp','started'),
 'completed':('completed','completed time','finished','finished time','end time'),
 'result':('result','outcome','status','backup status'),
}

def _words(s): return set(re.findall(r'[a-z0-9]+', normalize(s).replace('_',' ')))
def score_header(raw, canonical):
    r=normalize(raw).replace('_',' '); best=0.0
    for alias in TOKENS.get(canonical,(canonical,)):
        a=normalize(alias)
        if r==a: return 1.0
        rw,aw=_words(r),_words(a)
        if aw and aw<=rw: best=max(best,.88)
        elif rw and rw<=aw: best=max(best,.78)
        elif rw and aw: best=max(best,len(rw&aw)/len(rw|aw)*.72)
    return best

@dataclass(frozen=True)
class SchemaInference:
    role:str; confidence:str; score:float; mapping:dict[str,str]; signals:tuple[str,...]; sheet:Sheet

ROLE_FIELDS={
 'HR_ACTIVE_WORKER_ROSTER':(('employee id','employee'),('employment status',)),
 'IDENTITY_PROVIDER_EXPORT':(('user id','employee'),('status',)),
 'ASSET_INVENTORY':(('asset id','hostname','asset'),('edr',)),
 'ENDPOINT_PROTECTION_COVERAGE':(('asset','hostname'),('edr installed',)),
 'VULNERABILITY_REMEDIATION':(('finding',),('severity',)),
 'PRODUCTION_CHANGE_TICKETS':(('change','ticket'),('status',)),
 'USER_ACCESS_REVIEW':(('employee','user id'),('reviewer',),('review date',),('reviewer decision','status')),
 'BACKUP_JOB_REPORT':(('system',),('scheduled',),('result','status')),
}

def _values(sheet,col):
    idx=next((i for h,i in zip(sheet.headers,sheet.header_columns) if h==col),None)
    if not idx:return []
    return [r.cell(idx).text for r in sheet.data_rows if r.cell(idx) and r.cell(idx).text][:20]

def infer_sheet(sheet:Sheet):
    if not sheet.headers:return None
    best_for={}
    for canon in TOKENS:
        choices=sorted(((score_header(h,canon),h) for h in sheet.headers),reverse=True)
        if choices and choices[0][0]>=.55: best_for[canon]=choices[0]
    candidates=[]
    for role,groups in ROLE_FIELDS.items():
        selected={}; scores=[]; ok=True
        for group in groups:
            opts=[(best_for[c][0],c,best_for[c][1]) for c in group if c in best_for]
            if not opts: ok=False; break
            s,c,h=max(opts); selected[c]=h; scores.append(s)
        if not ok: continue
        # value signals reduce ambiguous HR/IdP and asset/EDR classifications
        vals=' '.join(v.lower() for h in sheet.headers for v in _values(sheet,h))
        bonus=0
        if role=='HR_ACTIVE_WORKER_ROSTER':
            if re.search(r'\bterminated|termination|employed|active employee\b',vals): bonus+=.12
            if 'termination effective' in best_for: bonus+=.10
        if role=='IDENTITY_PROVIDER_EXPORT' and re.search(r'\bactive|disabled|enabled|locked\b',vals): bonus=.08
        if role=='VULNERABILITY_REMEDIATION' and re.search(r'cve-\d{4}-\d+',vals): bonus=.12
        if role=='BACKUP_JOB_REPORT' and re.search(r'\bsuccess|successful|failed|failure\b',vals): bonus=.08
        # Preserve additional confidently mapped fields used by graph reconciliation.
        relevant={
          'VULNERABILITY_REMEDIATION':('ticket','status','hostname','asset'),
          'PRODUCTION_CHANGE_TICKETS':('change','ticket','status','finding','hostname','asset'),
          'ASSET_INVENTORY':('hostname','asset','edr'),
          'ENDPOINT_PROTECTION_COVERAGE':('hostname','asset','edr installed'),
          'HR_ACTIVE_WORKER_ROSTER':('employee','employee id','employment status','termination effective'),
          'IDENTITY_PROVIDER_EXPORT':('user id','employee','status'),
        }.get(role,())
        for c in relevant:
            if c in best_for and c not in selected: selected[c]=best_for[c][1]
        score=sum(scores)/len(scores)+bonus
        candidates.append((score,role,selected))
    if not candidates:return None
    candidates.sort(reverse=True); score,role,mapping=candidates[0]
    if len(candidates)>1 and score-candidates[1][0]<.05:return None
    conf='HIGH' if score>=.9 else 'MEDIUM' if score>=.72 else 'LOW'
    if conf=='LOW':return None
    return SchemaInference(role,conf,min(1.0,score),mapping,tuple(f'{k}←{v}' for k,v in mapping.items()),sheet)

def canonicalize_sheet(sheet:Sheet, inf:SchemaInference):
    reverse={v:k for k,v in inf.mapping.items()}
    headers=tuple(reverse.get(h,h) for h in sheet.headers)
    return Sheet(sheet.filename,sheet.name,sheet.rows,sheet.header_row,headers,sheet.header_columns)

def infer_workbook(book:Workbook):
    xs=[x for s in book.sheets if (x:=infer_sheet(s))]
    roles={x.role for x in xs}
    return xs[0] if len(roles)==1 and xs else None
