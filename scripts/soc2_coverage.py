#!/usr/bin/env python3
"""SOC 2 Trust Services Criteria coverage report (read-only).

Lists every criterion in knowledge/<framework>/framework/trust_services_criteria.json
against the controls and questionnaire questions in the knowledge base and reports
unmapped, duplicated and orphaned records. It never edits knowledge and never
decides that an uncovered criterion is "failed": uncovered means "no knowledge yet".

Usage: python scripts/soc2_coverage.py [--framework soc2] [--json]
Exit code is always 0 unless the knowledge files cannot be read.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(directory: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.json"))]


def analyse(root: Path) -> dict:
    index = json.loads((root / "framework" / "trust_services_criteria.json").read_text(encoding="utf-8"))
    series = {s["series_id"]: s for s in index["criteria_series"]}
    criteria = {c: s["series_id"] for s in index["criteria_series"] for c in s["criteria"]}

    controls = _load(root / "controls")
    questionnaires = _load(root / "questionnaires")
    questions = [dict(q, _questionnaire=qn["questionnaire_id"]) for qn in questionnaires for q in qn["questions"]]
    edges = [e for p in sorted((root / "mappings").glob("*.json"))
             for e in json.loads(p.read_text(encoding="utf-8")).get("mappings", [])]

    control_ids = [c["control_id"] for c in controls]
    question_ids = [q["question_id"] for q in questions]
    control_by_id = {c["control_id"]: c for c in controls}

    # criterion -> controls (record fields plus addresses_criterion edges)
    ctrl_crit: dict[str, set[str]] = defaultdict(set)
    for c in controls:
        for crit in [c.get("criterion"), *c.get("secondary_criteria", [])]:
            if crit:
                ctrl_crit[c["control_id"]].add(crit)
    edge_crit: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e.get("relationship") == "addresses_criterion":
            edge_crit[e["from"]["id"]].add(e["to"]["id"])

    crit_controls: dict[str, set[str]] = defaultdict(set)
    for cid, crits in ctrl_crit.items():
        for crit in crits:
            crit_controls[crit].add(cid)
    crit_questions: dict[str, set[str]] = defaultdict(set)
    for q in questions:
        for crit in q.get("related_criteria", []):
            crit_questions[crit].add(q["question_id"])

    r: dict = {}
    r["totals"] = dict(criteria=len(criteria), controls=len(controls), questions=len(questions),
                       edges=len(edges), questionnaires=len(questionnaires))

    per_series = {}
    for sid, s in series.items():
        crits = s["criteria"]
        per_series[sid] = dict(
            title=s["title"], criteria=len(crits),
            with_control=sum(1 for c in crits if c in crit_controls),
            with_question=sum(1 for c in crits if c in crit_questions))
    r["by_series"] = per_series

    r["unmapped"] = dict(
        no_control=sorted(c for c in criteria if c not in crit_controls),
        no_question=sorted(c for c in criteria if c not in crit_questions),
        control_without_question_coverage=sorted(c for c in crit_controls
                                                 if c in criteria and c not in crit_questions))

    dup = defaultdict(list)
    for e in edges:
        dup[(e["relationship"], e["from"]["id"], e["to"]["id"])].append(e["mapping_id"])
    seen_text = defaultdict(list)
    for q in questions:
        seen_text[" ".join(q["text"].lower().split())].append(q["question_id"])
    seen_name = defaultdict(list)
    for c in controls:
        seen_name[" ".join(c["control_name"].lower().split())].append(c["control_id"])
    primary = defaultdict(list)
    for c in controls:
        primary[c.get("criterion")].append(c["control_id"])
    r["duplicated"] = dict(
        control_ids=sorted({i for i in control_ids if control_ids.count(i) > 1}),
        question_ids=sorted({i for i in question_ids if question_ids.count(i) > 1}),
        edges=sorted(f"{'/'.join(k)}: {v}" for k, v in dup.items() if len(v) > 1),
        control_names=sorted(f"{k}: {v}" for k, v in seen_name.items() if len(v) > 1),
        question_texts=sorted(f"{v}" for v in seen_text.values() if len(v) > 1),
        multiple_primary_controls={k: v for k, v in sorted(primary.items()) if len(v) > 1},  # informational
    )

    orphans = defaultdict(list)
    for c in controls:
        cid = c["control_id"]
        if not ctrl_crit[cid]:
            orphans["control_without_criterion"].append(cid)
        for crit in ctrl_crit[cid] - set(criteria):
            orphans["control_unknown_criterion"].append(f"{cid} -> {crit}")
        if not c.get("questionnaire_questions"):
            orphans["control_without_question"].append(cid)
        for qid in c.get("questionnaire_questions", []):
            if qid not in question_ids:
                orphans["control_unknown_question"].append(f"{cid} -> {qid}")
        for crit in sorted(ctrl_crit[cid] - edge_crit[cid]):
            orphans["control_criterion_without_edge"].append(f"{cid} -> {crit}")
        for crit in sorted(edge_crit[cid] - ctrl_crit[cid]):
            orphans["edge_criterion_not_on_control_record"].append(f"{cid} -> {crit}")
    for q in questions:
        qid = q["question_id"]
        if not q.get("related_controls"):
            orphans["question_without_control"].append(qid)
        for cid in q.get("related_controls", []):
            if cid not in control_by_id:
                orphans["question_unknown_control"].append(f"{qid} -> {cid}")
            elif qid not in control_by_id[cid].get("questionnaire_questions", []):
                orphans["question_control_not_reciprocal"].append(f"{qid} -> {cid}")
            else:
                allowed = ctrl_crit[cid]
                for crit in q.get("related_criteria", []):
                    if crit not in allowed:
                        orphans["question_criterion_not_on_its_control"].append(f"{qid}: {crit} not in {cid}")
        for crit in q.get("related_criteria", []):
            if crit not in criteria:
                orphans["question_unknown_criterion"].append(f"{qid} -> {crit}")
    for qn in questionnaires:
        cited = {c for q in qn["questions"] for c in q.get("related_criteria", [])}
        declared = set(qn.get("covers_criteria", []))
        for crit in sorted(cited - declared):
            orphans["questionnaire_covers_missing"].append(f"{qn['questionnaire_id']}: {crit} cited by questions")
        for crit in sorted(declared - cited):
            orphans["questionnaire_covers_unused"].append(f"{qn['questionnaire_id']}: {crit} declared, no question")
    r["orphaned"] = dict(orphans)
    return r


def render(r: dict) -> str:
    out = []
    t = r["totals"]
    out.append(f"SOC 2 coverage: {t['criteria']} criteria, {t['controls']} controls, "
               f"{t['questions']} questions in {t['questionnaires']} questionnaires, {t['edges']} mapping edges")
    out.append("\nBy series (criteria | with control | with question)")
    for sid, s in r["by_series"].items():
        out.append(f"  {sid:<4} {s['criteria']:>2} | {s['with_control']:>2} | {s['with_question']:>2}  {s['title']}")
    out.append("\nUNMAPPED")
    for k, v in r["unmapped"].items():
        out.append(f"  {k} ({len(v)}): {', '.join(v) or '-'}")
    out.append("\nDUPLICATED")
    for k, v in r["duplicated"].items():
        out.append(f"  {k} ({len(v)}): {v or '-'}")
    out.append("\nORPHANED")
    if not r["orphaned"]:
        out.append("  none")
    for k, v in r["orphaned"].items():
        out.append(f"  {k} ({len(v)}):")
        out.extend(f"    - {x}" for x in v)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--framework", default="soc2", help="directory under knowledge/")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = analyse(REPO / "knowledge" / args.framework)
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
