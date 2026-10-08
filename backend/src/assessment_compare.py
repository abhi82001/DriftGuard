"""Presentation-only comparison of two saved assessments.

Counts and per-question status changes, with each side's provenance carried untouched.
No analysis and no verdict words: a changed status is reported as a change, nothing more.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


class CompareUnsupported(ValueError):
    """The saved state has no per-question areas to compare."""


@dataclass(frozen=True)
class Side:
    status: str = ""
    source_file: str = ""
    source_locator: str = ""
    source_snippet: str = ""


@dataclass(frozen=True)
class QuestionChange:
    question_id: str
    area: str
    base: Side | None      # None: question absent from that assessment
    other: Side | None

    @property
    def change(self) -> str:
        if self.base is None:
            return "ADDED"
        if self.other is None:
            return "REMOVED"
        return "CHANGED" if self.base.status != self.other.status else "UNCHANGED"


@dataclass(frozen=True)
class Comparison:
    base_counts: dict
    other_counts: dict
    changes: tuple[QuestionChange, ...]

    @property
    def unchanged(self) -> int:
        return sum(1 for c in self.changes if c.change == "UNCHANGED")


def _areas(obj) -> dict:
    areas = getattr(obj, "areas", None)
    if not isinstance(areas, (list, tuple)) or not all(hasattr(a, "question_id") and hasattr(a, "status") for a in areas):
        raise CompareUnsupported("This saved item has no per-question results to compare.")
    return {str(a.question_id): a for a in areas}


def _side(a) -> Side:
    return Side(str(a.status), str(getattr(a, "source_file", "") or ""),
                str(getattr(a, "source_locator", "") or ""), str(getattr(a, "source_snippet", "") or ""))


def compare_assessments(base, other) -> Comparison:
    b, o = _areas(base), _areas(other)
    order = list(b) + [q for q in o if q not in b]
    changes = tuple(
        QuestionChange(q, str(getattr(b.get(q) or o.get(q), "area", "")),
                       _side(b[q]) if q in b else None, _side(o[q]) if q in o else None)
        for q in order)
    return Comparison(dict(Counter(a.status for a in b.values())), dict(Counter(a.status for a in o.values())), changes)
