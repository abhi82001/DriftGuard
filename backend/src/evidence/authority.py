#!/usr/bin/env python3
"""Document authority, product scope and audit-period tagging.

Structural/filename + first-page signals only; nothing is guessed. A document
that matches no rule stays UNCLASSIFIED (for example a customer's own policy or
export) and keeps the legacy behaviour. Only ATTESTATION documents may establish
a control; contracts, privacy guidance, marketing and subprocessor lists may
inform context but never establish one. Unknown period stays NOT_EVALUATED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Optional

ATTESTATION = "ATTESTATION"
CONTRACT = "CONTRACT"
PRIVACY_GUIDANCE = "PRIVACY_GUIDANCE"
MARKETING = "MARKETING"
SUBPROCESSOR_LIST = "SUBPROCESSOR_LIST"
UNCLASSIFIED = "UNCLASSIFIED"

# Authorities that may establish a control.
ESTABLISHING = frozenset({ATTESTATION, UNCLASSIFIED})

PERIOD_COVERS = "COVERS_ASSESSMENT_DATE"
PERIOD_ENDED = "ENDED_BEFORE_ASSESSMENT"      # flagged, within freshness window
PERIOD_STALE = "STALE"
PERIOD_NOT_COVERING = "DOES_NOT_COVER"
PERIOD_UNKNOWN = "UNKNOWN"
PERIOD_BLOCKING = frozenset({PERIOD_STALE, PERIOD_NOT_COVERING})
FRESHNESS_DAYS = 365

# (scope label, filename keywords, third-party/subservice organisation?)
SCOPE_RULES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("DATABRICKS", ("databricks",), True),
    ("NUANCE", ("nuance",), True),
    ("AZURE_DEVOPS", ("azure devops",), False),
    ("M365_MICROSERVICES", ("microsoft 365 microservices",), False),
    ("M365_CENTRAL_SERVICES", ("microsoft 365 central",), False),
    ("M365", ("microsoft 365", "office 365", "o365", "m365"), False),
    ("AZURE", ("azure",), False),
)

_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}
_DATE_RE = re.compile(
    r"(?P<iso>(?P<iy>20\d{2})-(?P<im>\d{1,2})-(?P<id>\d{1,2}))"
    r"|(?P<us>(?P<um>\d{1,2})-(?P<ud>\d{1,2})-(?P<uy>20\d{2}))"
    r"|(?P<name>(?P<nm>[A-Za-z]{3,9})\.?\s+(?P<nd>\d{1,2}),?\s+(?P<ny>20\d{2}))")


@dataclass(frozen=True)
class DocumentAuthority:
    filename: str
    authority: str = UNCLASSIFIED
    report_type: str = ""            # SOC1_TYPE2, SOC2_TYPE1, SOC2_TYPE_UNSPECIFIED, BRIDGE_LETTER
    scope: str = ""                  # AZURE, M365, DATABRICKS, NUANCE, AZURE_DEVOPS ...
    third_party: bool = False        # subservice/third-party organisation report
    period_start: str = ""           # ISO date or ""
    period_end: str = ""

    @property
    def design_only(self) -> bool:
        return self.report_type.endswith("TYPE1")

    @property
    def scope_key(self) -> str:
        return f"{self.scope}|{self.report_type}" if (self.scope or self.report_type) else ""

    def period_state(self, as_of: date) -> str:
        end = _iso(self.period_end)
        if end is None:
            return PERIOD_UNKNOWN
        start = _iso(self.period_start)
        if start and as_of < start:
            return PERIOD_NOT_COVERING
        if as_of <= end:
            return PERIOD_COVERS
        return PERIOD_STALE if as_of - end > timedelta(days=FRESHNESS_DAYS) else PERIOD_ENDED

    def tag(self, as_of: Optional[date] = None) -> dict:
        d = asdict(self)
        d["design_only"] = self.design_only
        if as_of:
            d["period_state"] = self.period_state(as_of)
        return d


def _iso(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _dates(text: str) -> list[str]:
    out = []
    for m in _DATE_RE.finditer(text):
        try:
            if m.group("iso"):
                d = date(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
            elif m.group("us"):
                d = date(int(m.group("uy")), int(m.group("um")), int(m.group("ud")))
            else:
                month = _MONTHS.get(m.group("nm").lower())
                if month is None:
                    continue
                d = date(int(m.group("ny")), month, int(m.group("nd")))
        except ValueError:
            continue
        out.append(d.isoformat())
    return out


def _report_type(name: str, head: str) -> str:
    m = re.search(r"\bsoc\s*([12])\b", name)
    if not m:
        return ""
    t = re.search(r"\btype\s*(2|ii|1|i)\b", name) or re.search(r"\btype\s*(2|ii|1|i)\b", head[:1500])
    kind = "UNSPECIFIED" if not t else ("2" if t.group(1) in ("2", "ii") else "1")
    return f"SOC{m.group(1)}_TYPE{kind}"


def classify_document(filename: str, text_head: str = "") -> DocumentAuthority:
    name = filename.lower().rsplit(".", 1)[0]
    head = " ".join(text_head[:6000].lower().split())
    scope, third_party = "", False
    for label, keys, tp in SCOPE_RULES:
        if any(k in name for k in keys):
            scope, third_party = label, tp
            break

    def build(authority, report_type=""):
        start = end = ""
        found = _dates(filename.rsplit(".", 1)[0])
        if not found and authority == ATTESTATION and report_type != "BRIDGE_LETTER":
            i = head.find("period")
            found = _dates(text_head[max(i, 0):max(i, 0) + 400]) if i >= 0 else []
        if len(found) >= 2:
            start, end = found[0], found[1]
        elif len(found) == 1:
            end = found[0]
        return DocumentAuthority(filename, authority, report_type, scope,
                                 third_party, start, end)

    if "subprocessor" in name or "sub-processor" in name:
        return build(SUBPROCESSOR_LIST)
    if "bridge letter" in name:
        return build(ATTESTATION, "BRIDGE_LETTER")
    rt = _report_type(name, head)
    if rt:
        return build(ATTESTATION, rt)
    if any(k in name for k in ("privacy impact", "dpia", "privacy regulation", "user guide", "template")):
        return build(PRIVACY_GUIDANCE)
    if any(k in name for k in ("terms", "addendum", "contractual clauses", "agreement", "data protection")):
        return build(CONTRACT)
    if any(k in name for k in ("trust and innovation", "brochure", "whitepaper", "white paper",
                               "datasheet", "overview", "marketing")):
        return build(MARKETING)
    return DocumentAuthority(filename)


# Report types that carry attestation but cannot establish controls on their own.
NON_ESTABLISHING_REPORT_TYPES = frozenset({"BRIDGE_LETTER"})


def can_establish(auth: DocumentAuthority) -> tuple[bool, str]:
    """Return (eligible, reason-if-not). Period is checked separately."""
    if auth.authority not in ESTABLISHING:
        return False, f"{auth.authority.replace('_', ' ').lower()} informs context but cannot establish a control"
    if auth.report_type in NON_ESTABLISHING_REPORT_TYPES:
        return False, "a bridge letter extends a report's period but does not itself evidence controls"
    if auth.third_party:
        return False, (f"{auth.scope.title()} is a third-party/subservice report and cannot be credited "
                       "to customer-owned controls")
    return True, ""
