#!/usr/bin/env python3
"""Evidence-to-question audit trail: which file, fact and locator support which question.

Derived only from the facts already attached to each question (never inferred), so the
trail can always be rebuilt from a saved assessment. Presentation only: no analysis.
"""
from __future__ import annotations

import csv
import io

COLUMNS = ("question_id", "questionnaire_id", "area", "question_status", "file", "file_sha256",
           "locator", "fact_label", "fact", "excerpt", "extraction_method", "authority")


def build_audit_trail(result) -> dict:
    digests = {r["filename"]: r["sha256"] for r in (getattr(result, "run_stamp", None) or {}).get("input_files", [])}
    rows = []
    for a in result.areas:
        for f in a.known_facts:
            rows.append(dict(
                question_id=a.question_id, questionnaire_id=a.questionnaire_id, area=a.area,
                question_status=a.status, file=f.source_file, file_sha256=digests.get(f.source_file, ""),
                locator=f.source_locator, fact_label=f.label, fact=f.statement, excerpt=f.snippet,
                extraction_method=f.extraction_method, authority=getattr(f, "authority", "")))
    rows.sort(key=lambda r: (r["question_id"], r["file"], r["locator"], r["fact_label"], r["fact"]))
    return dict(
        assessment_id=result.assessment_id, vendor=result.vendor,
        input_hash=(getattr(result, "run_stamp", None) or {}).get("input_hash", ""),
        row_count=len(rows),
        questions_without_evidence=sorted(a.question_id for a in result.areas if not a.known_facts),
        rows=rows,
        note="Links show where each fact was read; they are observations, not compliance conclusions.")


def for_question(trail: dict, question_id: str) -> dict:
    rows = [r for r in trail["rows"] if r["question_id"] == question_id]
    return {**trail, "rows": rows, "row_count": len(rows), "question_id": question_id,
            "questions_without_evidence": [q for q in trail["questions_without_evidence"] if q == question_id]}


def _safe(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s.lstrip().startswith(("=", "+", "-", "@")) else s   # inert if opened in a spreadsheet


def to_csv(trail: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in trail["rows"]:
        w.writerow([_safe(r[c]) for c in COLUMNS])
    return out.getvalue()
