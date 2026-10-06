"""Optional evidence-date review against an explicitly supplied authoritative cutoff.

No machine-clock assumption; recorded timestamps are not affirmative confirmation.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def review_recorded_confirmation_dates(remediation_rows: Any, *, as_of: date) -> tuple[dict, ...]:
    """Flag parseable future timestamps without interpreting arbitrary notes.

    Rows are (row number, decision, ticket, status, confirmation). An as_of date
    must come from an authorized assessment context, never the server clock.
    """
    if not isinstance(as_of, date):
        raise TypeError("as_of must be an authoritative date")
    findings = []
    for row in remediation_rows:
        if len(row) != 5:
            raise ValueError("expected five fields per remediation row")
        number, _, _, _, raw = row
        value = str(raw or "").strip()
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace(" UTC", "+00:00").replace(" utc", "+00:00").replace("Z", "+00:00"))
        except ValueError:
            continue  # unknown terminology remains for human review, not inferred
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        if parsed.date() > as_of:
            findings.append({"row": number, "column": "H", "recorded_value": value,
                             "as_of": as_of.isoformat(), "state": "NEEDS_REVIEW",
                             "reason": "Recorded confirmation timestamp is later than the authoritative assessment cutoff; validate the source. Timestamp is not affirmative confirmation."})
    return tuple(findings)

CADENCE_DAYS={'daily':1,'weekly':7,'monthly':31,'quarterly':92,'semiannual':184,'semi-annually':184,'annual':366,'annually':366,'yearly':366}

def parse_evidence_date(value):
    """Conservative common-date parser used by CP016; ambiguous dates stay unknown."""
    if isinstance(value,date): return value
    s=str(value or '').strip()
    for fmt in ('%Y-%m-%d','%Y/%m/%d','%d-%b-%Y','%d %b %Y','%b %d, %Y','%d/%m/%Y'):
        try:return datetime.strptime(s,fmt).date()
        except ValueError:pass
    return None

def assess_freshness(value, cadence, *, as_of):
    d=parse_evidence_date(value); c=str(cadence or '').strip().lower()
    days=CADENCE_DAYS.get(c)
    if d is None:return {'state':'UNKNOWN','reason':'date could not be interpreted','date':None}
    if d>as_of:return {'state':'REJECTED','reason':'future-dated evidence','date':d.isoformat()}
    if days is None:return {'state':'UNKNOWN','reason':'cadence could not be interpreted','date':d.isoformat()}
    age=(as_of-d).days
    return {'state':'STALE' if age>days else 'CURRENT','reason':f'STALE EVIDENCE: {age} days old exceeds {c} cadence ({days} days)' if age>days else f'evidence is within {c} cadence','date':d.isoformat(),'age_days':age,'cadence_days':days}
