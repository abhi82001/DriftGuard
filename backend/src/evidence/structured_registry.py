"""Conservative structural recognition and row-quality checks for evidence registers.

A recognized schema means its rows can be quality-checked, NOT that its controls
are effective. Header combinations, never filenames, determine the evidence type.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from .model import EvidenceFact, Provenance, ValidationCheck, StructuredEvidenceResult, SUPPORTED, PARTIALLY_SUPPORTED, NEEDS_REVIEW, NOT_A_FAILURE
from .tabular import normalize

@dataclass(frozen=True)
class RegisterSpec:
    kind: str
    required: tuple[str, ...]
    key: str
    date_fields: tuple[str, ...] = ()
    critical_fields: tuple[str, ...] = ()
    classification_confidence: float = 1.0
    classification_signals: tuple[str, ...] = ()

SCHEMAS = (
    RegisterSpec('RISK_REGISTER', ('risk id','risk','inherent','treatment','residual','review date'), 'risk id', ('review date',), ('owner','status')),
    RegisterSpec('DATA_INVENTORY', ('dataset','classification','system','retention','deletion method'), 'dataset', (), ('owner',)),
    RegisterSpec('DATA_DELETION_RECORD', ('request','dataset','requested','completed','method','validator','status'), 'request', ('requested','completed'), ('validator','status')),
    RegisterSpec('FIREWALL_RULE_EXPORT', ('rule id','source','destination','port','action','expiry'), 'rule id', ('expiry','last review'), ('owner',)),
    RegisterSpec('ASSET_INVENTORY', ('asset id','hostname','environment','criticality','edr','encryption'), 'asset id', (), ('owner','status')),
    RegisterSpec('VULNERABILITY_REMEDIATION', ('finding','severity','owner','status'), 'finding', ('due date','closed date')),
    RegisterSpec('SECURITY_LOG_COVERAGE', ('source','expected assets','reporting','retention days','last event'), 'source', ('last event',), ('status',)),
    RegisterSpec('SECURITY_ALERT_TRIAGE', ('alert','severity','opened','first reviewed','disposition'), 'alert', ('opened','first reviewed'), ('analyst',)),
    RegisterSpec('TERMINATION_REPORT', ('employee','termination effective','iam case','current iam status'), 'employee', ('termination effective',)),
    RegisterSpec('IDENTITY_PROVIDER_EXPORT', ('user id','type','status','privileged','mfa enrolled'), 'user id'),
    RegisterSpec('PRIVILEGED_ACCOUNT_INVENTORY', ('account','account type','standing/jit','mfa','last review'), 'account', ('last review',), ('owner',)),
    RegisterSpec('PHYSICAL_ACCESS_REVIEW', ('person','facility','badge status','employment status','reviewer decision'), 'person', (), ('action status',)),
    RegisterSpec('PHYSICAL_ACCESS_ROSTER', ('person','worker status','facility','badge status','last review','reviewer','action'), 'person', ('last review',), ('reviewer',)),
    RegisterSpec('WORKER_LIFECYCLE_RECORD', ('worker','event','effective','iam ticket','completed','approver'), 'worker', ('effective','completed'), ('iam ticket','approver')),
    RegisterSpec('ENDPOINT_PROTECTION_COVERAGE', ('asset','class','expected','edr installed','last seen'), 'asset', ('last seen',), ('status',)),
    RegisterSpec('DISK_ENCRYPTION_REPORT', ('device','os','encryption','recovery key escrowed','last check'), 'device', ('last check',)),
    RegisterSpec('PRODUCTION_CHANGE_TICKETS', ('change','requester','approver','test evidence','implemented'), 'change', ('implemented',), ('status',)),
    RegisterSpec('BACKUP_JOB_REPORT', ('system','backup type','scheduled','completed','result'), 'system', ('scheduled','completed')),
    RegisterSpec('VENDOR_INVENTORY', ('vendor','service','risk tier','data access','last review'), 'vendor', ('last review',)),
    RegisterSpec('VISITOR_LOG', ('visitor','host','check in','check out','badge returned'), 'visitor', ('check in','check out')),
    RegisterSpec('UPTIME_REPORT', ('service','month','availability %','slo %','major incidents'), 'service'),
    RegisterSpec('CAPACITY_MONITORING', ('resource','threshold','peak','period','action'), 'resource'),
    RegisterSpec('HR_ACTIVE_WORKER_ROSTER', ('employee id','worker type','employment status','start date'), 'employee id', ('start date',)),
    RegisterSpec('BACKGROUND_CHECK_TRACKING', ('worker id','start date','check required','check completed'), 'worker id', ('start date',)),
    RegisterSpec('SECURITY_AWARENESS_TRAINING', ('employee','assigned','completed','score','status'), 'employee', ('assigned','completed')),
)

def recognize(workbook):
    # Exact schemas remain authoritative. CP016 only generalizes when exact recognition fails.
    candidates=[]
    for sheet in workbook.sheets:
        headers=set(sheet.headers)
        for spec in SCHEMAS:
            if set(spec.required).issubset(headers):
                candidates.append((spec,sheet))
    # Multiple different types in one workbook are ambiguous; do not guess.
    types={s.kind for s,_ in candidates}
    if len(types)==1 and candidates:
        return candidates[0]
    if not candidates:
        from .schema_generalization import infer_workbook, canonicalize_sheet
        inf=infer_workbook(workbook)
        if inf is not None:
            spec=next((s for s in SCHEMAS if s.kind==inf.role), None)
            if spec is None:
                # minimal generalized specs for graph/questionnaire evidence types
                extra={
                  'HR_ACTIVE_WORKER_ROSTER': RegisterSpec('HR_ACTIVE_WORKER_ROSTER',('employee','employment status'),'employee'),
                  'IDENTITY_PROVIDER_EXPORT': RegisterSpec('IDENTITY_PROVIDER_EXPORT',('user id','status'),'user id'),
                  'ENDPOINT_PROTECTION_COVERAGE': RegisterSpec('ENDPOINT_PROTECTION_COVERAGE',('asset','edr installed'),'asset'),
                  'VULNERABILITY_REMEDIATION': RegisterSpec('VULNERABILITY_REMEDIATION',('finding','severity'),'finding'),
                  'PRODUCTION_CHANGE_TICKETS': RegisterSpec('PRODUCTION_CHANGE_TICKETS',('change','status'),'change'),
                  'BACKUP_JOB_REPORT': RegisterSpec('BACKUP_JOB_REPORT',('system','scheduled','result'),'system',('scheduled',)),
                }; spec=extra.get(inf.role)
            if spec is not None:
                from dataclasses import replace
                spec=replace(spec,classification_confidence=inf.score,classification_signals=inf.signals)
                return spec, canonicalize_sheet(inf.sheet,inf)
    return None

def _date(value):
    if isinstance(value,datetime): return value.date()
    if isinstance(value,date): return value
    value=str(value).strip()
    for fmt in ('%Y-%m-%d','%Y-%m-%d %H:%M','%Y-%m-%d %H:%M:%S','%d/%m/%Y','%m/%d/%Y'):
        try: return datetime.strptime(value,fmt).date()
        except ValueError: pass
    return None

def analyze_register(workbook, spec, sheet, *, as_of=None):
    as_of = as_of or date.today()
    col={h:i for h,i in zip(sheet.headers,sheet.header_columns)}
    issues=[]; seen={}; facts=[]; rows=sheet.data_rows
    def issue(code, title, detail, row, field):
        cell=row.cell(col[field]) if field in col else None
        loc=cell.ref if cell else f'row {row.number}'
        issues.append(ValidationCheck(code,title,NEEDS_REVIEW,detail,{},spec.kind,
            (Provenance(workbook.filename,sheet.name,loc,cell.text if cell else ''),)))
    for row in rows:
        def val(field):
            cell=row.cell(col[field]) if field in col else None
            return cell.text.strip() if cell else ''
        key=val(spec.key)
        # Backup executions are runs, not systems. Prefer an explicit run/job id;
        # otherwise use a conservative composite identity so repeated backups for
        # one system on different schedules/times are not false duplicates.
        identity_key = key
        if spec.kind == 'BACKUP_JOB_REPORT':
            explicit = val('run id') or val('job id')
            identity_key = explicit or '|'.join((val('system'), val('scheduled'), val('backup type')))
        if not key:
            issue('KEY-MISSING','Missing record identifier',f'Row {row.number}: {spec.key} is blank; identify this record.',row,spec.key)
        elif identity_key in seen:
            issue('KEY-DUPLICATE','Duplicate record identifier',f'Rows {seen[identity_key]} and {row.number} share the same {spec.kind} record identity; reconcile rather than dropping a record.',row,spec.key)
        else: seen[identity_key]=row.number
        for field in spec.critical_fields:
            if field in col and not val(field):
                issue('FIELD-MISSING','Missing field',f'Row {row.number}: {field} is blank; confirm whether it is required for this record.',row,field)
        for field in spec.date_fields:
            if field not in col or not val(field): continue
            parsed=_date(val(field))
            if parsed is None:
                issue('DATE-INVALID','Unparseable date',f'Row {row.number}: {field} cannot be interpreted unambiguously; source value preserved.',row,field)
            elif parsed > as_of:
                issue('DATE-FUTURE','Future-dated field',f'Row {row.number}: {field} is {parsed.isoformat()}, after assessment date {as_of.isoformat()}; verify timing and field meaning.',row,field)
        # Domain checks concern the register's own record, not another control's effectiveness.
        if spec.kind == 'DATA_DELETION_RECORD':
            status=normalize(val('status'))
            completed=val('completed')
            if status in {'completed','closed','done'} and not completed:
                issue('DELETION-CLOSURE-UNSUPPORTED','Deletion completion lacks a date',
                      f'Row {row.number}: status is {val("status")!r} but completed is blank; obtain the completion record.',row,'status')
            requested=_date(val('requested')) if val('requested') else None
            finished=_date(completed) if completed else None
            if requested and finished and finished < requested:
                issue('DELETION-DATE-ORDER','Deletion completed before request',
                      f'Row {row.number}: completion predates the request; verify source timestamps.',row,'completed')
        elif spec.kind == 'RISK_REGISTER':
            inherent=normalize(val('inherent'))
            residual=normalize(val('residual'))
            ranks={'low':1,'medium':2,'moderate':2,'high':3,'critical':4}
            if inherent in ranks and residual in ranks and ranks[residual]>ranks[inherent]:
                issue('RISK-SCORE-REVIEW','Residual risk exceeds inherent risk',
                      f'Row {row.number}: reconcile scoring methodology and source values.',row,'residual')
            if normalize(val('status')) in {'closed','treated','mitigated'} and not val('treatment'):
                issue('RISK-TREATMENT-MISSING','Closed risk lacks treatment detail',
                      f'Row {row.number}: obtain the treatment decision and supporting record.',row,'status')
        elif spec.kind == 'FIREWALL_RULE_EXPORT':
            if normalize(val('action')) in {'allow','accept','permit'} and not val('expiry'):
                issue('RULE-EXPIRY-REVIEW','Allowed rule lacks expiry',
                      f'Row {row.number}: verify whether this is a permanent approved rule or missing expiry.',row,'action')
        elif spec.kind == 'BACKUP_JOB_REPORT':
            result=normalize(val('result'))
            if result in {'failed','failure','error','missed'}:
                issue('BACKUP-RUN-FAILED','Backup execution did not succeed',
                      f'Row {row.number}: {val("system") or "backup"} recorded result {val("result")!r}; review retry/remediation evidence.',row,'result')
            if 'restore tested' in col and normalize(val('restore tested')) in {'no','false','n','not tested'}:
                issue('RESTORE-NOT-VALIDATED','Restore not evidenced for this backup record',
                      f'Row {row.number}: backup execution is recorded but restore validation is not evidenced by this row.',row,'restore tested')
            completed=_date(val('completed')) if val('completed') else None
            cadence=normalize(val('backup type'))
            max_age={'daily':2,'weekly':9,'monthly':40}.get(cadence)
            if completed and max_age is not None and (as_of-completed).days > max_age:
                issue('BACKUP-RUN-STALE','Backup execution is stale for its stated cadence',
                      f'Row {row.number}: latest represented {val("backup type")} run completed {completed.isoformat()}, {(as_of-completed).days} days before assessment date.',row,'completed')
        elif spec.kind == 'VULNERABILITY_REMEDIATION':
            if normalize(val('status')) in {'closed','resolved','completed'} and 'closed date' in col and not val('closed date'):
                issue('VULN-CLOSURE-UNSUPPORTED','Closed finding lacks closure date',
                      f'Row {row.number}: request closure evidence.',row,'status')
            due=_date(val('due date')) if val('due date') else None
            closed=_date(val('closed date')) if val('closed date') else None
            if due and closed and closed>due:
                issue('VULN-LATE-CLOSURE','Finding closed after due date',
                      f'Row {row.number}: recorded closure is later than due date; review exception or extension.',row,'closed date')
        # Do not turn review date, treatment text, or row status into proof of other controls.
    if spec.kind == 'BACKUP_JOB_REPORT':
        backup_runs=[]
        restore_rows=[]
        for row in rows:
            def bval(field):
                cell=row.cell(col[field]) if field in col else None
                return cell.text.strip() if cell else ''
            rec={'system':bval('system'),'backup_type':bval('backup type'),'scheduled':bval('scheduled'),
                 'completed':bval('completed'),'result':bval('result')}
            if 'restore tested' in col: rec['restore_tested']=bval('restore tested')
            backup_runs.append(rec)
            if normalize(rec.get('restore_tested','')) in {'yes','true','y','tested','pass','passed'}:
                restore_rows.append(row.number)
        facts.append(EvidenceFact('backup_runs','Backup execution records',tuple(backup_runs),'records','stated',
            tuple(Provenance(workbook.filename,sheet.name,f'row {r.number}') for r in rows)))
        facts.append(EvidenceFact('restore_validated_rows','Backup rows with stated restore testing',tuple(restore_rows),'rows','counted',
            (Provenance(workbook.filename,sheet.name,'restore tested'),)))
    facts.append(EvidenceFact('record_count','Number of nonempty detail rows',len(rows),'count','counted',
        (Provenance(workbook.filename,sheet.name,f'rows after header {sheet.header_row or 0}'),)))
    facts.append(EvidenceFact('record_ids','Source record identifiers',tuple(val for val in seen),'text','counted',
        (Provenance(workbook.filename,sheet.name,spec.key),)))
    checks=tuple(issues) or (ValidationCheck('REGISTER-STRUCTURE','Register structure readable',SUPPORTED,
        f'{len(rows)} records read with recognized {spec.kind} columns. This is structural quality only, not proof of operating effectiveness.',{},spec.kind),)
    return StructuredEvidenceResult(filename=workbook.filename,evidence_type=spec.kind,knowledge_evidence_id='',
        state=NEEDS_REVIEW if issues else SUPPORTED,needs_review=bool(issues),facts=tuple(facts),checks=checks,
        notes=(f'{spec.kind}: structural data-quality review only; no control effectiveness or questionnaire sufficiency inferred.',NOT_A_FAILURE),
        classification_confidence=spec.classification_confidence,matched_signals=spec.classification_signals or spec.required,extractor='schema-register-v1')
