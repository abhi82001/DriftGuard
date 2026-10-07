#!/usr/bin/env python3
"""Deterministic extractors for operational evidence exports (IdP, HRIS, Jira, scanner...).

Same boundary as extractors/user_access_review.py: structure announces the type
(header *synonyms*, never filenames or body text), rows are read with provenance,
and every finding is a deterministic comparison against a stated rule. A file that
matches no kind here stays UNCLASSIFIED upstream - unread material, never a failure.
A finding is a "needs review" signal about records, not an audit conclusion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

from .model import (
    NEEDS_REVIEW, NOT_A_FAILURE, SUPPORTED, EvidenceFact, Provenance,
    StructuredEvidenceResult, ValidationCheck,
)
from .tabular import Sheet, Workbook, is_tabular, normalize, read_tabular, TabularError

ACCESS_REVIEW_LOG = "ACCESS_REVIEW_LOG"
PRIVILEGED_APPROVAL_LIST = "PRIVILEGED_APPROVAL_LIST"
BACKUP_JOB_REPORT = "BACKUP_JOB_REPORT"
CHANGE_POPULATION = "CHANGE_POPULATION"
INCIDENT_REGISTER = "INCIDENT_REGISTER"
VENDOR_REGISTER = "VENDOR_REGISTER"
TRAINING_RECORDS = "TRAINING_RECORDS"
VULNERABILITY_REMEDIATION = "VULNERABILITY_REMEDIATION"

SOURCE = "operational-register-v1"

# Canonical field -> header synonyms, compared with punctuation/case squashed out
# (so employee_id, Employee ID and employeeId are one header).
SYNONYMS: dict[str, tuple[str, ...]] = {
    "id": ("id", "userid", "employeeid", "empid", "workerid", "staffid", "personid"),
    "email": ("email", "login", "username", "upn", "mail", "emailaddress"),
    "decision": ("decision", "reviewdecision", "reviewresult", "certification"),
    "reviewer": ("reviewer", "reviewedby", "certifier"),
    "review_date": ("reviewdate", "revieweddate", "reviewedon", "certificationdate"),
    "approved_by": ("approvedby", "approver", "authorizedby", "sponsor"),
    "approved_date": ("approveddate", "approvedon", "approvaldate"),
    "job_id": ("jobid", "runid", "backupid", "executionid"),
    "run_date": ("rundate", "backupdate", "runtime", "started", "scheduled", "timestamp"),
    "status": ("status", "state", "result", "outcome", "backupstatus"),
    "resource": ("resource", "system", "asset", "server", "workload", "target"),
    "incident_id": ("incidentid", "incident", "incidentkey"),
    "detected": ("detected", "detectedon", "detecteddate", "reported", "opened"),
    "severity": ("severity", "priority"),
    "postmortem": ("postmortemref", "postmortem", "postmortemid", "rca", "rootcause", "postincidentreview"),
    "change_key": ("key", "changeid", "change", "ticket", "ticketid"),
    "author": ("author", "requester", "createdby", "developer"),
    "approver": ("approver", "approvedby", "changeapprover"),
    "approval_date": ("approvaldate", "approveddate", "approvedon"),
    "code_reviewer": ("codereviewer", "peerreviewer", "reviewer", "reviewedby"),
    "ci_status": ("cistatus", "buildstatus", "pipelinestatus", "testresult", "ci"),
    "deployed_date": ("deployeddate", "deployedon", "implemented", "releasedate", "deploymentdate"),
    "vendor_id": ("vendorid", "supplierid"),
    "risk_tier": ("risktier", "tier", "criticality", "riskrating"),
    "last_assessment": ("lastassessment", "lastassessed", "lastreview", "assessmentdate", "lastreviewed"),
    "next_due": ("nextdue", "nextreview", "nextassessment", "reassessmentdue", "reviewdue"),
    "completed_date": ("completeddate", "completedon", "completiondate", "completed"),
    "finding_id": ("findingid", "vulnerabilityid", "vulnid", "finding"),
    "first_seen": ("firstseen", "discovered", "firstdetected", "detecteddate"),
    "sla_due": ("sladue", "sladate", "remediationdue", "duedate", "due"),
    "closed_date": ("closeddate", "remediateddate", "resolveddate", "closedon"),
    "last_login": ("lastlogin", "lastlogindate", "lastactive", "lastsignin"),
    "mfa": ("mfaenrolled", "mfaenabled", "mfa", "mfastatus"),
    "group": ("group", "groups", "role", "roles", "privilegegroup"),
    "employment_status": ("employmentstatus", "workerstatus", "hrstatus"),
    "termination_date": ("terminationdate", "terminatedon", "terminationeffective", "lastday", "enddate"),
}

# Each kind needs every listed field; a tuple means "any one of these".
KIND_FIELDS: dict[str, tuple] = {
    ACCESS_REVIEW_LOG: (("id", "email"), "decision", "reviewer", "review_date"),
    PRIVILEGED_APPROVAL_LIST: (("id", "email"), "approved_by", "approved_date"),
    BACKUP_JOB_REPORT: ("job_id", "run_date", "status", "resource"),
    CHANGE_POPULATION: ("change_key", "author", "approver", "approval_date", "deployed_date"),
    INCIDENT_REGISTER: ("incident_id", "detected", "severity", "postmortem"),
    VENDOR_REGISTER: ("vendor_id", "risk_tier", "last_assessment", "next_due"),
    TRAINING_RECORDS: (("id", "email"), "completed_date", "status"),
    VULNERABILITY_REMEDIATION: ("finding_id", "severity", "first_seen", "sla_due", "status"),
}

EVIDENCE_ID: dict[str, str] = {}   # these types map onto questionnaire questions, not knowledge records

_SLA_DAYS = {"critical": 15, "high": 30, "medium": 90, "moderate": 90, "low": 180}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", normalize(text))


def map_headers(headers: Iterable[str]) -> dict[str, str]:
    """canonical field -> source header; earlier synonyms win. A header may serve two
    canonical fields (e.g. `approver`), so kind detection, not mapping, disambiguates."""
    squashed = {h: _squash(h) for h in headers}
    mapping: dict[str, str] = {}
    for canon, names in SYNONYMS.items():
        for name in names:                       # earlier synonyms are stronger
            hit = next((h for h, s in squashed.items() if s == name), None)
            if hit:
                mapping[canon] = hit
                break
    return mapping


def detect(sheet: Sheet) -> Optional[str]:
    mapping = map_headers(sheet.headers)
    for kind, fields in KIND_FIELDS.items():
        if all((any(f in mapping for f in field) if isinstance(field, tuple) else field in mapping)
               for field in fields):
            return kind
    return None


# ------------------------------------------------------------------ row access
@dataclass(frozen=True)
class Rec:
    number: int
    values: dict[str, str]

    def get(self, field: str) -> str:
        return self.values.get(field, "")


def read_records(sheet: Sheet, mapping: Optional[dict[str, str]] = None) -> list[Rec]:
    mapping = mapping or map_headers(sheet.headers)
    columns = dict(zip(sheet.headers, sheet.header_columns))
    out = []
    for row in sheet.data_rows:
        values = {}
        for canon, header in mapping.items():
            cell = row.cell(columns[header])
            values[canon] = cell.text.strip() if cell is not None else ""
        out.append(Rec(row.number, values))
    return out


def parse_date(text: str) -> Optional[date]:
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:19] if "T" in fmt or " " in fmt else text, fmt).date()
        except ValueError:
            continue
    return None


def _is_true(text: str) -> bool:
    return normalize(text) in {"true", "yes", "y", "1", "enrolled", "enabled"}


# -------------------------------------------------------------------- findings
@dataclass(frozen=True)
class Finding:
    code: str
    title: str
    detail: str
    records: tuple[tuple[int, str], ...]     # (row number, record identifier)


def _f(code, title, detail, records) -> Optional[Finding]:
    return Finding(code, title, detail, tuple(records)) if records else None


def _id(rec: Rec, *fields: str) -> str:
    return next((rec.get(f) for f in fields if rec.get(f)), f"row {rec.number}")


def _check_access_review(recs, as_of):
    incomplete = [(r.number, _id(r, "id", "email")) for r in recs
                  if not (r.get("decision") and r.get("reviewer") and r.get("review_date"))]
    return [_f("REVIEW-ROW-INCOMPLETE", "Review row lacks decision, reviewer or date",
               "Each reviewed account needs a recorded decision, reviewer and date.", incomplete)]


def _check_priv_approval(recs, as_of):
    gaps = [(r.number, _id(r, "id", "email")) for r in recs
            if not (r.get("approved_by") and r.get("approved_date"))]
    return [_f("PRIVILEGE-APPROVAL-INCOMPLETE", "Privileged approval lacks approver or date",
               "A privileged-user approval must name the approver and the date.", gaps)]


def _check_backup(recs, as_of):
    failed = [r for r in recs if normalize(r.get("status")) in {"failed", "failure", "error", "missed"}]
    out = [_f("BACKUP-RUN-FAILED", "Backup job failed",
              "A failed backup run is recorded; confirm retry evidence.",
              [(r.number, f"{r.get('job_id')} {r.get('run_date')}") for r in failed])]
    # Daily cadence only when the data itself is daily; never assume it otherwise.
    by_resource: dict[str, list[date]] = {}
    for r in recs:
        d = parse_date(r.get("run_date"))
        if d:
            by_resource.setdefault(r.get("resource"), []).append(d)
    missing = []
    for resource, days in by_resource.items():
        days = sorted(set(days))
        if len(days) < 14 or sum((b - a).days == 1 for a, b in zip(days, days[1:])) < 0.8 * (len(days) - 1):
            continue
        have = set(days)
        d = days[0]
        while d <= days[-1]:
            if d not in have:
                missing.append((0, f"{resource} {d.isoformat()}"))
            d += timedelta(days=1)
    out.append(_f("BACKUP-RUN-MISSING", "No backup job recorded for a scheduled day",
                  "The data shows daily backups, but no job exists for these days.", missing))
    return out


def _check_changes(recs, as_of):
    deployed = [r for r in recs if r.get("deployed_date")]
    no_approval = [(r.number, r.get("change_key")) for r in deployed if not r.get("approver")]
    late = []
    for r in deployed:
        a, d = parse_date(r.get("approval_date")), parse_date(r.get("deployed_date"))
        if r.get("approver") and a and d and a > d:
            late.append((r.number, r.get("change_key")))
    selfrev = [(r.number, r.get("change_key")) for r in deployed
               if r.get("code_reviewer") and normalize(r.get("code_reviewer")) == normalize(r.get("author"))]
    failed_ci = [(r.number, r.get("change_key")) for r in deployed
                 if normalize(r.get("ci_status")) in {"fail", "failed", "failure", "error"}]
    return [
        _f("CHANGE-NO-APPROVAL", "Change deployed without approval",
           "No approver is recorded for a deployed change.", no_approval),
        _f("CHANGE-APPROVAL-AFTER-DEPLOY", "Approval dated after deployment",
           "Approval must precede deployment.", late),
        _f("CHANGE-SELF-REVIEWED", "Code reviewer is the author",
           "Independent review is required.", selfrev),
        _f("CHANGE-DEPLOYED-FAILED-CI", "Deployed with failing CI", "CI must pass before deploy.", failed_ci),
    ]


def _check_incidents(recs, as_of):
    open_words = {"open", "investigating", "in progress", "active"}
    return [_f("INCIDENT-NO-POSTMORTEM", "Incident lacks a postmortem reference",
               "Every closed incident needs a postmortem.",
               [(r.number, r.get("incident_id")) for r in recs
                if not r.get("postmortem") and normalize(r.get("status")) not in open_words])]


def _check_vendors(recs, as_of):
    never = [(r.number, r.get("vendor_id")) for r in recs if not r.get("last_assessment")]
    overdue = []
    for r in recs:
        last, due = parse_date(r.get("last_assessment")), parse_date(r.get("next_due"))
        if (last and (as_of - last).days > 365) or (due and due < as_of):
            overdue.append((r.number, r.get("vendor_id")))
    return [_f("VENDOR-NO-REVIEW", "Vendor has no assessment recorded", "A review date is missing.", never),
            _f("VENDOR-REVIEW-OVERDUE", "Vendor reassessment overdue",
               "Vendors are reassessed every 12 months.", overdue)]


def _check_training(recs, as_of):
    open_ = []
    for r in recs:
        done = normalize(r.get("status")) in {"complete", "completed", "done", "passed"}
        when = parse_date(r.get("completed_date"))
        if not done or not when or (as_of - when).days > 365:
            open_.append((r.number, _id(r, "id", "email")))
    return [_f("TRAINING-NOT-COMPLETED", "Security training missing or overdue",
               "Annual security training is required for all staff.", open_)]


def _check_vulns(recs, as_of):
    breached = []
    for r in recs:
        due = parse_date(r.get("sla_due"))
        if due is None:
            continue
        closed = parse_date(r.get("closed_date"))
        closed_state = normalize(r.get("status")) in {"closed", "resolved", "remediated", "fixed"}
        if (closed_state and closed and closed > due) or (not closed_state and due < as_of):
            breached.append((r.number, r.get("finding_id")))
    return [_f("VULN-SLA-BREACH", "Finding open or closed past its SLA",
               "Remediation SLAs: Critical 15d, High 30d, Medium 90d, Low 180d.", breached)]


CHECKS: dict[str, Callable] = {
    ACCESS_REVIEW_LOG: _check_access_review, PRIVILEGED_APPROVAL_LIST: _check_priv_approval,
    BACKUP_JOB_REPORT: _check_backup, CHANGE_POPULATION: _check_changes,
    INCIDENT_REGISTER: _check_incidents, VENDOR_REGISTER: _check_vendors,
    TRAINING_RECORDS: _check_training, VULNERABILITY_REMEDIATION: _check_vulns,
}


# ----------------------------------------------------------------- result build
def _provenance(workbook, sheet, records, limit=25):
    return tuple(Provenance(workbook.filename, sheet.name, f"row {n}" if n else "derived", ident)
                 for n, ident in records[:limit])


def recognize_operational(workbook: Workbook) -> Optional[tuple[str, Sheet]]:
    """Single unambiguous operational register in the workbook, else None."""
    hits = [(k, s) for s in workbook.sheets if s.headers and (k := detect(s))]
    return hits[0] if len(hits) == 1 else None


def analyze_operational(workbook: Workbook, kind: str, sheet: Sheet, *, as_of: Optional[date] = None
                        ) -> StructuredEvidenceResult:
    as_of = as_of or date.today()
    recs = read_records(sheet)
    findings = [f for f in CHECKS[kind](recs, as_of) if f]
    facts = [EvidenceFact("record_count", "Number of nonempty detail rows", len(recs), "count", "counted",
                          (Provenance(workbook.filename, sheet.name, f"rows after header {sheet.header_row or 0}"),))]
    checks = []
    for f in findings:
        facts.append(EvidenceFact(f.code.lower().replace("-", "_") + "_count", f.title, len(f.records),
                                  "count", "computed", _provenance(workbook, sheet, f.records)))
        checks.append(ValidationCheck(f.code, f.title, NEEDS_REVIEW,
                                      f"{len(f.records)} record(s): {f.detail}",
                                      {"records": [i for _, i in f.records]}, kind,
                                      _provenance(workbook, sheet, f.records)))
    if not checks:
        checks.append(ValidationCheck("REGISTER-STRUCTURE", "Register read with no rule deviations", SUPPORTED,
                                      f"{len(recs)} records read; no deviation from the stated rules at {as_of}.",
                                      {}, kind))
    return StructuredEvidenceResult(
        filename=workbook.filename, evidence_type=kind, knowledge_evidence_id="",
        state=NEEDS_REVIEW if findings else SUPPORTED, needs_review=bool(findings),
        facts=tuple(facts), checks=tuple(checks), notes=(NOT_A_FAILURE,),
        classification_confidence=1.0, matched_signals=tuple(sorted(map_headers(sheet.headers))),
        extractor=SOURCE)


# --------------------------------------------------------- cross-file reconcile
def _load(payloads, roles: dict[str, Callable[[dict], bool]]):
    """role -> (filename, sheet name, records) for the first sheet whose mapping satisfies the role."""
    found = {}
    for name, data in payloads:
        if not is_tabular(name):
            continue
        try:
            book = read_tabular(name, data)
        except TabularError:
            continue
        for sheet in book.sheets:
            mapping = map_headers(sheet.headers)
            for role, test in roles.items():
                if role not in found and test(mapping):
                    found[role] = (name, sheet.name, read_records(sheet, mapping))
    return found


_ROLES = {
    "idp": lambda m: {"status", "last_login", "mfa", "group"} <= m.keys() and ("id" in m or "email" in m),
    "hris": lambda m: {"employment_status", "termination_date"} <= m.keys(),
    "approved": lambda m: {"approved_by", "approved_date"} <= m.keys(),
    "review": lambda m: {"decision", "review_date"} <= m.keys(),
}


def _key(rec: Rec) -> str:
    return normalize(rec.get("id") or rec.get("email"))


def _keys(rec: Rec) -> set[str]:
    return {normalize(v) for v in (rec.get("id"), rec.get("email")) if v}


def reconcile(payloads, *, as_of: Optional[date] = None) -> list[tuple[str, Finding]]:
    """Cross-file findings as (question_id, Finding). Needs the files each rule compares."""
    as_of = as_of or date.today()
    roles = _load(payloads, _ROLES)
    out: list[tuple[str, Finding]] = []
    idp = roles.get("idp")
    if not idp:
        return out
    idp_name, _, users = idp
    active = [u for u in users if normalize(u.get("status")) in {"active", "enabled"}]

    def add(qid, finding):
        if finding:
            out.append((qid, finding))

    add("QN-ACCESS-001-Q01", _f("MFA-NOT-ENROLLED", "Active user without MFA",
                                "Policy: MFA required for all users.",
                                [(u.number, _id(u, "id", "email")) for u in active if not _is_true(u.get("mfa"))]))
    terminated: dict[str, Optional[date]] = {}
    if "hris" in roles:
        for h in roles["hris"][2]:
            if normalize(h.get("employment_status")) in {"terminated", "inactive", "separated", "former"}:
                for k in _keys(h):
                    terminated[k] = parse_date(h.get("termination_date"))
        add("QN-ACCESS-001-Q06", _f("TERMINATED-USER-ACTIVE", "Terminated worker still active in the IdP",
                                    "Policy: terminated users deprovisioned within 1 day.",
                                    [(u.number, _id(u, "id", "email")) for u in active
                                     if (k := next((k for k in _keys(u) if k in terminated), None))
                                     and (terminated[k] is None or (as_of - terminated[k]).days > 1)]))
    # Already reported as terminated-but-active, so not repeated as dormant.
    add("QN-ACCESS-001-Q05", _f("DORMANT-ACCOUNT-90D", "Active account with no login for over 90 days",
                                "Policy: accounts inactive >90 days are disabled.",
                                [(u.number, _id(u, "id", "email")) for u in active
                                 if not (_keys(u) & terminated.keys())
                                 and (d := parse_date(u.get("last_login"))) and (as_of - d).days > 90]))
    # Privileged group membership counts whatever the account status: a deprovisioned
    # account that still sits in the admin group is a privileged-access record to explain.
    admins = [u for u in users if "admin" in normalize(u.get("group"))]
    if "approved" in roles:
        approved = set().union(*(_keys(a) for a in roles["approved"][2])) if roles["approved"][2] else set()
        add("QN-ACCESS-001-Q08", _f("UNAPPROVED-PRIVILEGED-USER", "Privileged account not on the approved list",
                                    "Policy: privileged users must be approved by the CISO.",
                                    [(u.number, _id(u, "id", "email")) for u in admins
                                     if not (_keys(u) & approved)]))
        known = set().union(*(_keys(u) for u in users)) if users else set()
        add("QN-ACCESS-001-Q08", _f("ORPHAN-PRIVILEGE-APPROVAL", "Approved privileged user has no IdP account",
                                    "The approval record matches no identity in the IdP export.",
                                    [(a.number, _id(a, "id", "email")) for a in roles["approved"][2]
                                     if not (_keys(a) & known)]))
    if "review" in roles:
        rev = roles["review"][2]
        reviewed = set().union(*(_keys(r) for r in rev)) if rev else set()
        add("QN-ACCESS-001-Q04", _f("USER-MISSING-FROM-REVIEW", "Active user absent from the access review",
                                    "Policy: the quarterly review covers 100% of users.",
                                    [(u.number, _id(u, "id", "email")) for u in active if not (_keys(u) & reviewed)]))
        revoked = {k for r in rev if normalize(r.get("decision")) in {"revoke", "remove", "revoked"}
                   for k in _keys(r)}
        add("QN-ACCESS-001-Q05", _f("REVOKE-NOT-REMEDIATED", "Revoke decision but the account is still active",
                                    "Policy: revoke decisions are remediated.",
                                    [(u.number, _id(u, "id", "email")) for u in active if _keys(u) & revoked]))
    return out
