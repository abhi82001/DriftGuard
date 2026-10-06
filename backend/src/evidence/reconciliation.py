"""Conservative, provenance-preserving joins between recognized register schemas.

A match is only a shared explicit record identifier; descriptions, dates and
filenames are never used as surrogate keys. Reconciliation flags are review
requests, not evidence of control failure or effectiveness.
"""
from __future__ import annotations
from dataclasses import dataclass
from .tabular import normalize

@dataclass(frozen=True)
class JoinIssue:
    relationship: str
    code: str
    identifier: str
    source_file: str
    source_row: int
    detail: str

# Only joins whose source and target contain the SAME explicit identifier are allowed.
RELATIONSHIPS = (
    ('DATA_INVENTORY', 'DATA_DELETION_RECORD', 'dataset'),
    ('ASSET_INVENTORY', 'ENDPOINT_PROTECTION_COVERAGE', 'asset id'),
)

def _records(workbook, sheet, key):
    col = sheet.column_of(key)
    if col is None:
        return None
    result = {}
    for row in sheet.data_rows:
        cell = row.cell(col)
        value = normalize(cell.text) if cell else ''
        if value:
            result.setdefault(value, []).append(row.number)
    return result

def reconcile(artifacts):
    """artifacts: iterable of (kind, Workbook, Sheet); no fuzzy matching.

    Returns (issues, unsupported_relationships). Missing join columns are
    explicitly unsupported, never interpreted as missing operational records.
    """
    indexed = {}
    for kind, workbook, sheet in artifacts:
        indexed.setdefault(kind, []).append((workbook, sheet))
    issues, unsupported = [], []
    for left, right, key in RELATIONSHIPS:
        if left not in indexed or right not in indexed:
            continue
        for lw, ls in indexed[left]:
            for rw, rs in indexed[right]:
                left_ids = _records(lw, ls, key)
                right_ids = _records(rw, rs, key)
                relationship = f'{left} ↔ {right}'
                if left_ids is None or right_ids is None:
                    unsupported.append(f'{relationship}: exact shared {key!r} column unavailable; no inferred join')
                    continue
                for identifier, rows in right_ids.items():
                    if identifier not in left_ids:
                        for row in rows:
                            issues.append(JoinIssue(relationship, 'UNMATCHED-EXPLICIT-ID', identifier,
                                rw.filename, row, f'No {left} row has the same explicit {key} value. Verify scope and identifiers.'))
                for identifier, rows in left_ids.items():
                    if len(rows) > 1:
                        issues.append(JoinIssue(relationship, 'AMBIGUOUS-SOURCE-ID', identifier,
                            lw.filename, rows[0], f'{key} occurs on multiple source rows {rows}; no arbitrary match made.'))
    return tuple(issues), tuple(unsupported)
