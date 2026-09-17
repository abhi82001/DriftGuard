#!/usr/bin/env python3
"""Deterministic USER_ACCESS_REVIEW fact extraction (CP007 Phase 1).

Two reading strategies run over the same workbook:

  * key/value labels on a summary sheet ("Excluded Accounts" -> B11), and
  * row aggregation over a detail sheet (count the Review Decision column).

Both are recorded with provenance. When they agree, the fact is corroborated
twice; when they disagree, the fact is marked as a conflict and DriftGuard does
not choose a winner - that is a matter for the validation layer and, ultimately,
for a human.

This extractor performs no reconciliation arithmetic and reaches no conclusion.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

from ..classify import USER_ACCESS_REVIEW, Classification
from ..model import EvidenceFact, Provenance
from ..tabular import Cell, Row, Sheet, Workbook, column_letter, normalize
from .base import register

FACT_LABELS: dict[str, str] = {
    "campaign_name": "campaign / review name",
    "campaign_status": "campaign status",
    "review_period_start": "review period start",
    "review_period_end": "review period end",
    "review_completed_date": "review completed date",
    "reviewer": "reviewer",
    "source_population": "source population",
    "excluded_population": "excluded population",
    "reviewed_population": "reviewed (certified) population",
    "identity_populations": "identity populations / types",
    "identity_unrecognized": "identity values not recognised as an identity type",
    "decision_retain": "reviewer decision: retain",
    "decision_modify": "reviewer decision: modify",
    "decision_revoke": "reviewer decision: revoke",
    "decision_investigate": "reviewer decision: investigate",
    "decision_unrecognized": "rows without a recognised reviewer decision",
    "remediation_completed": "remediation completed",
    "remediation_open": "remediation open (stated)",
    "exceptions_open": "exceptions / open items",
    "remediation_ticket_reference": "remediation ticket reference",
    "remediation_applicable_rows": "rows recording remediation activity",
    "remediation_confirmed_rows": "remediation rows with post-change confirmation",
    "remediation_unconfirmed_rows": "remediation rows without post-change confirmation",
}

FACT_ORDER = tuple(FACT_LABELS)

COUNT_FACTS = frozenset({
    "source_population", "excluded_population", "reviewed_population",
    "decision_retain", "decision_modify", "decision_revoke",
    "decision_investigate", "remediation_completed", "remediation_open",
    "exceptions_open",
})

# Counts that only ever come from row aggregation: no summary label produces
# them, so they are never coerced from a stated key/value pair.
ROW_COUNT_FACTS = frozenset({
    "identity_unrecognized", "decision_unrecognized",
    "remediation_applicable_rows", "remediation_confirmed_rows",
    "remediation_unconfirmed_rows",
})
DATE_FACTS = frozenset({"review_period_start", "review_period_end", "review_completed_date"})
DECISION_FACTS = ("decision_retain", "decision_modify", "decision_revoke",
                  "decision_investigate")

# Exact labels only. A label that is not listed here produces no fact at all,
# so an unfamiliar export is read as incomplete rather than guessed at.
_LABEL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "campaign_name": ("campaign name", "campaign", "campaign id", "review name"),
    "campaign_status": ("campaign status", "review status", "status"),
    "review_period_start": ("review period start", "period start", "period from",
                            "review period from"),
    "review_period_end": ("review period end", "period end", "period to",
                          "review period to"),
    "review_completed_date": ("review completed date", "review date", "completed on",
                              "date completed", "completion date"),
    "reviewer": ("reviewer", "certifier", "review owner"),
    "source_population": ("source population", "total accounts", "accounts extracted",
                          "population extracted", "extracted accounts",
                          "total population"),
    "excluded_population": ("excluded accounts", "excluded population", "exclusions",
                            "accounts excluded", "out of scope accounts"),
    "reviewed_population": ("reviewed accounts", "certified accounts",
                            "reviewed / certified accounts", "reviewed population",
                            "accounts reviewed", "in scope accounts"),
    "decision_retain": ("decision: retain", "retain", "retained", "no change"),
    "decision_modify": ("decision: modify", "modify", "modified", "reduce access"),
    "decision_revoke": ("decision: revoke", "revoke", "revoked", "remove access"),
    "decision_investigate": ("decision: investigate", "investigate",
                             "flagged for investigation", "under investigation"),
    "remediation_completed": ("remediation completed", "remediation closed",
                              "revocations completed", "changes completed",
                              "completed remediation"),
    "remediation_open": ("remediation open", "open remediation",
                         "outstanding remediation", "remediation outstanding"),
    "exceptions_open": ("open exceptions", "exceptions", "open items",
                        "unresolved items", "open findings"),
}

# Longest label first so "remediation completed" is never shadowed by "remediation".
_LABEL_INDEX: tuple[tuple[str, str], ...] = tuple(sorted(
    ((synonym, key) for key, synonyms in _LABEL_SYNONYMS.items() for synonym in synonyms),
    key=lambda pair: len(pair[0]), reverse=True,
))

_DECISION_VALUES: dict[str, str] = {
    "retain": "decision_retain", "retained": "decision_retain",
    "keep": "decision_retain", "no change": "decision_retain",
    "certify": "decision_retain", "certified": "decision_retain",
    "modify": "decision_modify", "modified": "decision_modify",
    "reduce": "decision_modify", "reduced": "decision_modify",
    "revoke": "decision_revoke", "revoked": "decision_revoke",
    "remove": "decision_revoke", "removed": "decision_revoke",
    "investigate": "decision_investigate", "investigated": "decision_investigate",
    "flag": "decision_investigate", "flagged": "decision_investigate",
}

_REMEDIATION_COMPLETED = frozenset({"completed", "complete", "closed", "done",
                                    "applied", "confirmed", "remediated"})
_REMEDIATION_OPEN = frozenset({"open", "pending", "in progress", "in-progress",
                               "not started", "outstanding", "awaiting"})

# A closed set of affirmative tokens for the post-change confirmation column.
# Anything else in that column - a timestamp, a note, "NOT AVAILABLE", a blank -
# is not read as a confirmation. There is no pattern matching here on purpose:
# guessing that some other string means "confirmed" would be an interpretation,
# and interpretation is not the extractor's job.
_CONFIRMATION_AFFIRMATIVE = frozenset({"yes", "y", "true", "confirmed",
                                       "verified", "complete", "completed"})

_IDENTITY_TYPES: tuple[tuple[str, str], ...] = (
    ("service", "service_account"),
    ("machine", "service_account"),
    ("privileg", "privileged"),
    ("admin", "privileged"),
    ("contractor", "contractor"),
    ("vendor", "third_party"),
    ("third party", "third_party"),
    ("employee", "employee"),
    ("staff", "employee"),
    ("intern", "intern"),
    ("shared", "shared_account"),
)

_DECISION_HEADERS = ("review decision", "decision", "reviewer decision",
                     "certification decision", "reviewer action")
_IDENTITY_HEADERS = ("identity type", "account type", "identity", "user type",
                     "principal type")
_REMEDIATION_STATUS_HEADERS = ("remediation status", "closure status",
                               "ticket status", "remediation state")
_TICKET_HEADERS = ("remediation ticket", "ticket", "ticket id", "change record",
                   "change ticket", "closure record")
_POST_CHANGE_HEADERS = ("post-change confirmed", "post change confirmed",
                        "post-change confirmation", "system confirmation",
                        "access removal confirmed", "removal verified")
_EXCLUSION_SHEET_WORDS = ("exclusion", "excluded", "out of scope", "out-of-scope")

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


# --------------------------------------------------------------- value coercion
def _label_key(text: str) -> Optional[str]:
    label = _PARENTHETICAL.sub("", normalize(text)).strip()
    for synonym, key in _LABEL_INDEX:
        if label == synonym:
            return key
    return None


def _as_count(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = normalize(value).replace(",", "").replace(" ", "")
    return int(text) if text.isdigit() else None


def _as_date(value: Any) -> Optional[str]:
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.strftime("%Y-%m-%d")
    text = normalize(value)
    return text or None


def _excerpt(label: str, value: Any) -> str:
    return f"{' '.join(str(label).split())}: {value}"[:160]


# ------------------------------------------------------------------ observation
class _Observation:
    __slots__ = ("key", "value", "provenance", "derivation")

    def __init__(self, key: str, value: Any, provenance: Provenance, derivation: str):
        self.key = key
        self.value = value
        self.provenance = provenance
        self.derivation = derivation


# ------------------------------------------------------------------- extractor
class UserAccessReviewExtractor:
    """Reads a user access review export without interpreting it."""

    evidence_type = USER_ACCESS_REVIEW
    source = "deterministic-tabular"

    def extract(
        self, workbook: Workbook, classification: Classification
    ) -> list[EvidenceFact]:
        observations: list[_Observation] = []
        for sheet in workbook.sheets:
            observations.extend(self._key_values(sheet))
            observations.extend(self._aggregate(sheet))
            observations.extend(self._exclusion_sheet(sheet))
        return _merge(observations)

    # ---------------------------------------------------------- key/value pairs
    @staticmethod
    def _key_values(sheet: Sheet) -> list[_Observation]:
        out: list[_Observation] = []
        for row in sheet.rows:
            filled = row.filled
            if len(filled) < 2:
                continue
            label_cell, value_cell = filled[0], filled[1]
            if not isinstance(label_cell.value, str):
                continue
            key = _label_key(label_cell.text)
            if key is None:
                continue
            value = _coerce(key, value_cell.value)
            if value is None:
                continue
            out.append(_Observation(
                key, value,
                Provenance(sheet.filename, sheet.name, value_cell.ref,
                           _excerpt(label_cell.text, value_cell.text)),
                "stated",
            ))
        return out

    # ------------------------------------------------------------ row aggregation
    @staticmethod
    def _aggregate(sheet: Sheet) -> list[_Observation]:
        if sheet.header_row is None:
            return []
        decision_column = sheet.column_of(*_DECISION_HEADERS)
        if decision_column is None:
            return []

        rows = sheet.data_rows
        if not rows:
            return []
        span = _span(sheet, rows)
        out: list[_Observation] = [_Observation(
            "reviewed_population", len(rows),
            Provenance(sheet.filename, sheet.name, span,
                       f"{len(rows)} reviewed rows"),
            "counted",
        )]

        # Only decision categories actually present in the column are reported.
        # An absent category is not observed as zero: that would be a guess.
        counts = _count_column(rows, decision_column, _DECISION_VALUES)
        letter = column_letter(decision_column)
        for key in DECISION_FACTS:
            if key in counts:
                out.append(_Observation(
                    key, counts[key],
                    Provenance(sheet.filename, sheet.name, f"{span} column {letter}",
                               f"{counts[key]} rows"),
                    "counted",
                ))

        # No row is dropped silently. Every reviewed row either lands in one of
        # the decision counts above or is counted here, so the two always add up
        # to the reviewed population. What an unrecognised value means is left
        # to the validator and, ultimately, to a human.
        unrecognized = _unmatched_rows(rows, decision_column, _DECISION_VALUES)
        out.append(_Observation(
            "decision_unrecognized", len(unrecognized),
            Provenance(sheet.filename, sheet.name,
                       f"{_rows_phrase(unrecognized) or span} column {letter}",
                       _samples(unrecognized) or f"0 of {len(rows)} rows"),
            "counted",
        ))

        identity_column = sheet.column_of(*_IDENTITY_HEADERS)
        if identity_column is not None:
            identity_letter = column_letter(identity_column)
            breakdown, unknown = _identity_breakdown(rows, identity_column)
            if breakdown:
                out.append(_Observation(
                    "identity_populations", breakdown,
                    Provenance(sheet.filename, sheet.name,
                               f"{span} column {identity_letter}",
                               ", ".join(f"{k}={v}" for k, v in breakdown)),
                    "counted",
                ))
            # A value that matches no known identity type is counted as
            # unrecognised rather than turned into an identity type of its own.
            out.append(_Observation(
                "identity_unrecognized", len(unknown),
                Provenance(sheet.filename, sheet.name,
                           f"{_rows_phrase(unknown) or span} column {identity_letter}",
                           _samples(unknown) or f"0 of {len(rows)} rows"),
                "counted",
            ))

        status_column = sheet.column_of(*_REMEDIATION_STATUS_HEADERS)
        if status_column is not None:
            status_letter = column_letter(status_column)
            states = _remediation_breakdown(rows, status_column)
            for key, count in states:
                out.append(_Observation(
                    key, count,
                    Provenance(sheet.filename, sheet.name,
                               f"{span} column {status_letter}", f"{count} rows"),
                    "counted",
                ))

        ticket_column = sheet.column_of(*_TICKET_HEADERS)
        if ticket_column is not None:
            out.append(_Observation(
                "remediation_ticket_reference", True,
                Provenance(sheet.filename, sheet.name,
                           f"{column_letter(ticket_column)}{sheet.header_row}",
                           sheet.headers[sheet.header_columns.index(ticket_column)]),
                "counted",
            ))

        # The presence of a confirmation column used to be reported as a boolean,
        # which said that somebody had provided a column - not that anything in it
        # confirmed anything. It is now counted per row.
        confirmation_column = sheet.column_of(*_POST_CHANGE_HEADERS)
        if confirmation_column is not None:
            confirmation_letter = column_letter(confirmation_column)
            applicable, confirmed, unconfirmed = _confirmation_counts(
                rows, confirmation_column, ticket_column, status_column)
            for key, matched in (("remediation_applicable_rows", applicable),
                                 ("remediation_confirmed_rows", confirmed),
                                 ("remediation_unconfirmed_rows", unconfirmed)):
                phrase = _rows_phrase(matched) or span
                out.append(_Observation(
                    key, len(matched),
                    Provenance(sheet.filename, sheet.name,
                               f"{phrase} column {confirmation_letter}",
                               _samples(matched) or f"0 of {len(rows)} rows"),
                    "counted",
                ))
        return out

    # ------------------------------------------------------------ exclusion sheet
    @staticmethod
    def _exclusion_sheet(sheet: Sheet) -> list[_Observation]:
        name = normalize(sheet.name)
        if not any(word in name for word in _EXCLUSION_SHEET_WORDS):
            return []
        if sheet.header_row is None:
            return []
        rows = sheet.data_rows
        if not rows:
            return []
        return [_Observation(
            "excluded_population", len(rows),
            Provenance(sheet.filename, sheet.name, _span(sheet, rows),
                       f"{len(rows)} excluded accounts listed"),
            "counted",
        )]


def _coerce(key: str, value: Any) -> Any:
    if key in COUNT_FACTS:
        return _as_count(value)
    if key in DATE_FACTS:
        return _as_date(value)
    text = " ".join(str(value).split()) if value is not None else ""
    return text or None


def _span(sheet: Sheet, rows: tuple[Row, ...]) -> str:
    first, last = rows[0].number, rows[-1].number
    return f"row {first}" if first == last else f"rows {first}-{last}"


def _cell_text(row: Row, column: int) -> str:
    cell: Optional[Cell] = row.cell(column)
    return normalize(cell.text) if cell is not None else ""


def _count_column(rows, column: int, mapping: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = mapping.get(_cell_text(row, column))
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _unmatched_rows(rows, column: int, mapping: dict[str, str]) -> tuple[tuple[int, str], ...]:
    """Rows whose value in `column` maps to nothing, blanks included.

    A blank decision cell is as much a row without a recognised decision as a
    cell reading "Excluded", so both are reported here. Together with
    `_count_column` this accounts for every row exactly once.
    """
    return tuple((row.number, _cell_text(row, column)) for row in rows
                 if mapping.get(_cell_text(row, column)) is None)


def _identity_breakdown(
    rows, column: int
) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[int, str], ...]]:
    """Split the column into recognised identity types and unrecognised values.

    An unrecognised value is returned separately instead of being slugified into
    a population of its own: inventing an identity type out of a cell DriftGuard
    does not understand would put a fact in the report that the artifact never
    stated. Blank cells are neither: they are simply not values.
    """
    counts: dict[str, int] = {}
    unknown: list[tuple[int, str]] = []
    for row in rows:
        text = _cell_text(row, column)
        if not text:
            continue
        name = next((label for fragment, label in _IDENTITY_TYPES if fragment in text),
                    None)
        if name is None:
            unknown.append((row.number, text))
            continue
        counts[name] = counts.get(name, 0) + 1
    return tuple(sorted(counts.items())), tuple(unknown)


def _confirmation_counts(rows, confirmation: int, ticket: Optional[int],
                         status: Optional[int]):
    """Count remediation rows and how many carry a post-change confirmation.

    A row is remediation-applicable when the artifact records remediation
    activity for it in any of the remediation columns it provides (ticket,
    status or the confirmation column itself). Of those, a row counts as
    confirmed only when its confirmation cell holds one of a closed set of
    affirmative tokens.
    """
    columns = [c for c in (ticket, status, confirmation) if c is not None]
    applicable: list[tuple[int, str]] = []
    confirmed: list[tuple[int, str]] = []
    unconfirmed: list[tuple[int, str]] = []
    for row in rows:
        if not any(_cell_text(row, c) for c in columns):
            continue
        text = _cell_text(row, confirmation)
        applicable.append((row.number, text))
        target = confirmed if text in _CONFIRMATION_AFFIRMATIVE else unconfirmed
        target.append((row.number, text))
    return tuple(applicable), tuple(confirmed), tuple(unconfirmed)


def _rows_phrase(matched: tuple[tuple[int, str], ...]) -> str:
    numbers = [number for number, _ in matched]
    if not numbers:
        return ""
    if len(numbers) == 1:
        return f"row {numbers[0]}"
    return "rows " + ", ".join(str(n) for n in numbers[:12]) + (
        f" (+{len(numbers) - 12} more)" if len(numbers) > 12 else "")


def _samples(matched: tuple[tuple[int, str], ...]) -> str:
    """The offending cell values themselves, so a reviewer can go and look."""
    if not matched:
        return ""
    shown = ", ".join(f"row {number}: {text or '(blank)'}" for number, text in matched[:8])
    if len(matched) > 8:
        shown = f"{shown}, +{len(matched) - 8} more"
    return shown[:160]


def _remediation_breakdown(rows, column: int) -> tuple[tuple[str, int], ...]:
    completed = open_items = 0
    for row in rows:
        text = _cell_text(row, column)
        if text in _REMEDIATION_COMPLETED:
            completed += 1
        elif text in _REMEDIATION_OPEN:
            open_items += 1
    out = []
    if completed or open_items:
        out.append(("remediation_completed", completed))
        out.append(("remediation_open", open_items))
    return tuple(out)


# ----------------------------------------------------------------------- merge
def _merge(observations: list[_Observation]) -> list[EvidenceFact]:
    """Collapse observations per fact key, preserving disagreement as a conflict."""
    grouped: dict[str, list[_Observation]] = {}
    for observation in observations:
        grouped.setdefault(observation.key, []).append(observation)

    facts: list[EvidenceFact] = []
    for key in FACT_ORDER:
        group = grouped.get(key)
        if not group:
            continue
        distinct = []
        for observation in group:
            if observation.value not in distinct:
                distinct.append(observation.value)
        provenance = tuple(o.provenance for o in group)
        derivations = sorted({o.derivation for o in group})

        if len(distinct) > 1:
            facts.append(EvidenceFact(
                key=key, label=FACT_LABELS[key], value=None,
                unit=_unit(key), derivation="+".join(derivations),
                provenance=provenance, conflict=True,
                conflicting_values=tuple((o.value, o.provenance) for o in group),
            ))
        else:
            facts.append(EvidenceFact(
                key=key, label=FACT_LABELS[key], value=distinct[0],
                unit=_unit(key), derivation="+".join(derivations),
                provenance=provenance,
            ))
    return facts


def _unit(key: str) -> str:
    if key in COUNT_FACTS or key in ROW_COUNT_FACTS:
        return "count"
    if key in DATE_FACTS:
        return "date"
    if key == "identity_populations":
        return "breakdown"
    if key == "remediation_ticket_reference":
        return "flag"
    return "text"


register(UserAccessReviewExtractor())
