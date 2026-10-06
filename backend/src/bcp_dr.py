"""BCP/DR/backup intelligence (CP011).

Extracts and reconciles recovery evidence.  Results are evidence observations,
never SOC 2 conclusions.  Every observation retains source provenance.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable
from ingestion import Document, Chunk
from narrative_intelligence import FactProvenance, classify_source_role

@dataclass(frozen=True)
class RecoveryFact:
    key: str
    value: object
    subject: str
    evidence_role: str
    provenance: FactProvenance

@dataclass(frozen=True)
class RecoveryIssue:
    code: str
    state: str
    detail: str
    provenance: tuple[FactProvenance, ...]

@dataclass(frozen=True)
class RecoveryAssessment:
    facts: tuple[RecoveryFact, ...]
    issues: tuple[RecoveryIssue, ...]

_DUR = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*(?P<u>hours?|hrs?|h|minutes?|mins?|m)\b", re.I)
_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")

def _prov(c: Chunk, excerpt: str|None=None):
    page=c.locator.split()[-1] if c.locator.startswith('page ') else ''
    section=c.heading or ''
    return FactProvenance(c.filename,c.locator,excerpt or c.text,page=page,section=section,
                          paragraph=c.locator if c.locator.startswith('paragraph ') else '',
                          table=c.locator if 'table ' in c.locator else '')

def _minutes(text: str):
    total=0.0; found=False
    for m in _DUR.finditer(text):
        found=True; n=float(m.group('n')); u=m.group('u').lower()
        total += n*60 if u.startswith('h') else n
    return int(round(total)) if found else None

def extract_recovery_facts(documents: Iterable[Document]) -> list[RecoveryFact]:
    out=[]
    for d in documents:
        role=classify_source_role(d)
        low=d.text.lower()
        if 'business continuity' in low:
            c=next((x for x in d.chunks if 'business continuity' in x.text.lower()),d.chunks[0])
            out.append(RecoveryFact('bcp_plan_exists',True,'business continuity',role,_prov(c)))
        if 'disaster recovery' in low or re.search(r'\bRTO\b|\bRPO\b',d.text):
            c=next((x for x in d.chunks if 'disaster recovery' in x.text.lower()),d.chunks[0])
            out.append(RecoveryFact('dr_plan_or_test_exists',True,'disaster recovery',role,_prov(c)))
        for c in d.chunks:
            t=c.text
            # Recovery objectives in narrative plans: "API: RTO 4 hours, RPO 1 hour"
            for m in re.finditer(r'(?P<subject>[A-Za-z][A-Za-z0-9 _-]{1,60}?):\s*RTO\s*(?P<rto>\d+(?:\.\d+)?\s*(?:hours?|h|minutes?|m))\s*,?\s*RPO\s*(?P<rpo>\d+(?:\.\d+)?\s*(?:hours?|h|minutes?|m))',t,re.I):
                subject=m.group('subject').strip().lower()
                out += [RecoveryFact('target_rto_minutes',_minutes(m.group('rto')),subject,'PLAN_OBJECTIVE',_prov(c,m.group(0))),
                        RecoveryFact('target_rpo_minutes',_minutes(m.group('rpo')),subject,'PLAN_OBJECTIVE',_prov(c,m.group(0)))]
            # CP016: phrasing-independent objective/measurement extraction.
            # The labels (RTO/RPO/recovery/data loss) carry semantics; units are normalized separately.
            for m in re.finditer(r'(?P<label>RTO|recovery time objective)\s*(?:target|objective|is|=|:)?\s*(?P<dur>\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m))',t,re.I):
                out.append(RecoveryFact('target_rto_minutes',_minutes(m.group('dur')),'recovery program','PLAN_OBJECTIVE',_prov(c,m.group(0))))
            for m in re.finditer(r'(?P<label>RPO|recovery point objective)\s*(?:target|objective|is|=|:)?\s*(?P<dur>\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m))',t,re.I):
                out.append(RecoveryFact('target_rpo_minutes',_minutes(m.group('dur')),'recovery program','PLAN_OBJECTIVE',_prov(c,m.group(0))))
            for m in re.finditer(r'(?:actual|measured|observed)?\s*(?:recovery|restoration)(?:\s+(?:completed|time|duration))?\s*(?:was|in|took|=|:)?\s*(?P<dur>\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m))',t,re.I):
                out.append(RecoveryFact('actual_recovery_minutes',_minutes(m.group('dur')),'recovery program','TEST_RESULT',_prov(c,m.group(0))))
            for m in re.finditer(r'(?:actual|measured|observed)?\s*(?:data loss|recovery point|data-loss)(?:\s+(?:was|duration))?\s*(?:was|=|:)?\s*(?P<dur>\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|m))',t,re.I):
                out.append(RecoveryFact('observed_data_loss_minutes',_minutes(m.group('dur')),'recovery program','TEST_RESULT',_prov(c,m.group(0))))
            cad=re.search(r'\btested\s+at\s+least\s+(annually|quarterly|monthly)|\b(exercised\s+periodically)\b',t,re.I)
            if cad: out.append(RecoveryFact('testing_cadence',cad.group(0), 'recovery program','PLAN_OBJECTIVE',_prov(c,cad.group(0))))
            if re.search(r'corrective action|action item|remediation',t,re.I):
                for m in re.finditer(r'(?:corrective action|action item|remediation)\s+([A-Z]+-\d+).*?status\s+(Open|Closed|Completed)',t,re.I):
                    out.append(RecoveryFact('remediation_status',m.group(2).lower(),m.group(1),'TEST_RESULT',_prov(c,m.group(0))))
            dm=re.search(r'(?:exercise|test) date:\s*(20\d{2}-\d{2}-\d{2})',t,re.I)
            if dm: out.append(RecoveryFact('dr_test_date',dm.group(1),'disaster recovery','TEST_RESULT',_prov(c,dm.group(0))))
            # PDF table text extraction: subject, target RTO, actual, target RPO, loss, result
            # Capture known row shape after headers, tolerant of newlines.
            if role=='TEST_RESULT' and ('Target RTO' in t and 'Actual Recovery' in t):
                body=t.replace('\r','')
                pat=re.compile(r'\n(?P<s>[A-Za-z][A-Za-z ]+?)\n(?P<tr>\d+h(?:\s*\d+m)?)\n(?P<ar>\d+h(?:\s*\d+m)?)\n(?P<tp>\d+h(?:\s*\d+m)?)\n(?P<loss>\d+h(?:\s*\d+m)?|\d+m)\n(?P<res>Met|RPO Miss|RTO Miss|Failed)',re.I)
                matches=list(pat.finditer(body))
                if not matches:
                    tail=re.split(r'\bResult\b',body,flags=re.I,maxsplit=1)[-1]
                    flat=re.compile(r'(?P<s>[A-Za-z][A-Za-z ]*?)\s+(?P<tr>\d+h(?:\s*\d+m)?)\s+(?P<ar>\d+h(?:\s*\d+m)?)\s+(?P<tp>\d+h(?:\s*\d+m)?)\s+(?P<loss>\d+h(?:\s*\d+m)?|\d+m)\s+(?P<res>Met|RPO Miss|RTO Miss|Failed)',re.I)
                    matches=list(flat.finditer(tail))
                for m in matches:
                    subject=m.group('s').strip().lower()
                    ex=m.group(0).strip()
                    out += [RecoveryFact('test_target_rto_minutes',_minutes(m.group('tr')),subject,'TEST_RESULT',_prov(c,ex)),
                            RecoveryFact('actual_recovery_minutes',_minutes(m.group('ar')),subject,'TEST_RESULT',_prov(c,ex)),
                            RecoveryFact('test_target_rpo_minutes',_minutes(m.group('tp')),subject,'TEST_RESULT',_prov(c,ex)),
                            RecoveryFact('observed_data_loss_minutes',_minutes(m.group('loss')),subject,'TEST_RESULT',_prov(c,ex)),
                            RecoveryFact('test_outcome',m.group('res').lower(),subject,'TEST_RESULT',_prov(c,ex))]
        # Explicit program metadata. Absence stays absence; filenames never invent values.
        for key,rx in [
            ('plan_owner',r'(?:plan owner|owner)\s*[:=-]\s*([^\n|.;]+)'),
            ('approval',r'(?:approved by|approval)\s*[:=-]\s*([^\n|.;]+)'),
            ('review_date',r'(?:review date|last reviewed)\s*[:=-]\s*(20\d{2}-\d{2}-\d{2})'),
            ('critical_services',r'(?:critical services?|critical customer services?)\s*[:=-]?\s*([^\n.;]+)'),
            ('business_impact_assumptions',r'(?:business impact|impact assumption)[^\n.;]*'),
            ('recovery_strategy',r'(?:recovery strategy|recovery procedures?)[^\n.;]*'),
            ('recovery_location',r'(?:recovery location|alternate site|secondary region)\s*[:=-]?\s*([^\n.;]+)'),
            ('dr_responsibilities',r'(?:dr responsibilities|disaster recovery responsibilities)[^\n.;]*'),
            ('retention',r'(?:backup retention|retention)\s*[:=-]?\s*([^\n.;]+)'),
            ('offsite_isolated_backup',r'(?:offsite|isolated|immutable|air[- ]?gapped)\s+backup[^\n.;]*'),
            ('test_scenario',r'(?:test scenario|exercise scenario)\s*[:=-]?\s*([^\n.;]+)'),
            ('remediation_owner',r'(?:remediation owner|action owner)\s*[:=-]\s*([^\n|.;]+)'),
            ('remediation_due_date',r'(?:remediation due|due date)\s*[:=-]\s*(20\d{2}-\d{2}-\d{2})'),
            ('restore_result',r'(?:restore test|restoration test).{0,50}(?:result|status)\s*[:=-]?\s*(passed|failed|successful|success)'),
        ]:
            m=re.search(rx,d.text,re.I)
            if m:
                token=m.group(0).split()[0].lower()
                c=next((x for x in d.chunks if token in x.text.lower()),d.chunks[0])
                val=m.group(1).strip() if m.lastindex else m.group(0).strip()
                out.append(RecoveryFact(key,val,'recovery program',role,_prov(c,m.group(0))))
        # responsibilities/dependencies/communications are kept only when explicitly stated.
        for key,rx in [('recovery_responsibilities',r'continuity responsibilities[^.]*'),('dependencies',r'dependency management[^.]*'),('communication_escalation',r'communications?[^,.]*')]:
            m=re.search(rx,d.text,re.I)
            if m:
                c=next(x for x in d.chunks if m.group(0).split()[0].lower() in x.text.lower())
                out.append(RecoveryFact(key,m.group(0), 'business continuity',role,_prov(c,m.group(0))))
    return out

def _subject_key(s: str) -> str:
    s=re.sub(r'\b(?:critical|customer|supporting|service|system|disaster|recovery|plan)\b',' ',s.lower())
    return ' '.join(s.split())

def reconcile_recovery(facts: Iterable[RecoveryFact], *, as_of: date|None=None, stale_days: int=400) -> RecoveryAssessment:
    facts=tuple(facts); issues=[]; as_of=as_of or date.today()
    def by(k): return [f for f in facts if f.key==k]
    # Reconcile plan objectives with test-declared targets using conservative normalized service names.
    for pk,tk,label in [('target_rto_minutes','test_target_rto_minutes','RTO'),('target_rpo_minutes','test_target_rpo_minutes','RPO')]:
        for plan in by(pk):
            test=next((f for f in by(tk) if _subject_key(f.subject)==_subject_key(plan.subject)),None)
            if test and plan.value != test.value:
                issues.append(RecoveryIssue('OBJECTIVE-MISMATCH','CONFLICT',f'{plan.subject}: plan {label} {plan.value}m differs from test target {test.value}m.',(plan.provenance,test.provenance)))
    plan_subjects={_subject_key(f.subject):f for f in by('target_rto_minutes')}
    test_subjects={_subject_key(f.subject):f for f in by('test_target_rto_minutes')}
    for subject,f in test_subjects.items():
        if plan_subjects and subject not in plan_subjects:
            issues.append(RecoveryIssue('SYSTEM-SCOPE-MISMATCH','NEEDS_REVIEW',f'Tested recovery subject {f.subject!r} has no matching plan objective in supplied evidence.',(f.provenance,)))
    owners=by('plan_owner')
    distinct={str(f.value).strip().lower() for f in owners if str(f.value).strip()}
    if len(distinct)>1:
        issues.append(RecoveryIssue('OWNERSHIP-INCONSISTENT','CONFLICT','Supplied recovery documents name inconsistent plan owners.',tuple(f.provenance for f in owners)))
    # Compare test-observed objectives using the test's own targets. This avoids fuzzy subject matching.
    for actual in by('actual_recovery_minutes'):
        target=next((f for f in by('test_target_rto_minutes') if f.subject==actual.subject),None) or next((f for f in by('target_rto_minutes') if _subject_key(f.subject)==_subject_key(actual.subject)),None)
        if target and actual.value > target.value:
            issues.append(RecoveryIssue('OBJECTIVE_NOT_MET','NEEDS_REVIEW',f'{actual.subject}: actual recovery {actual.value}m exceeds target RTO {target.value}m.',(target.provenance,actual.provenance)))
    for loss in by('observed_data_loss_minutes'):
        target=next((f for f in by('test_target_rpo_minutes') if f.subject==loss.subject),None) or next((f for f in by('target_rpo_minutes') if _subject_key(f.subject)==_subject_key(loss.subject)),None)
        if target and loss.value > target.value:
            issues.append(RecoveryIssue('OBJECTIVE_NOT_MET','NEEDS_REVIEW',f'{loss.subject}: observed data loss {loss.value}m exceeds target RPO {target.value}m.',(target.provenance,loss.provenance)))
    for f in by('dr_test_date'):
        try: d=datetime.strptime(str(f.value),'%Y-%m-%d').date()
        except ValueError: continue
        if (as_of-d).days > stale_days:
            issues.append(RecoveryIssue('DR-TEST-STALE','NEEDS_REVIEW',f'Latest evidenced DR test date {d.isoformat()} is more than {stale_days} days before assessment date.',(f.provenance,)))
    for f in by('remediation_status'):
        if str(f.value).lower() not in {'closed','completed','resolved'}:
            issues.append(RecoveryIssue('DR-REMEDIATION-OPEN','NEEDS_REVIEW',f'{f.subject} remains {f.value}; obtain closure evidence.',(f.provenance,)))
    # Plan/test separation: no issue merely because one exists; explicitly surface missing restore validation only when backups exist elsewhere.
    return RecoveryAssessment(facts,tuple(issues))
