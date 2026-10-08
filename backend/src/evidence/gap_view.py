"""Presentation of gaps: grouped by requested document, prioritised, exportable.

Presentation only. It re-arranges what ``build_question_reports`` already decided
(statuses, missing items, provenance) and attaches one remediation line taken
verbatim from knowledge/soc2 remediation definitions. It performs no analysis and
emits no verdict words.
"""
from __future__ import annotations

import csv
import html
import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from .report import GAP_KIND_LABELS, NOTHING_FURTHER, build_question_reports

NO_GUIDANCE = "No guidance available"
UNREADABLE = "UNREADABLE_FILE"

# Lower tier = higher priority: conflicts, then missing, then partial/insufficient,
# then unreadable files (fixable by re-upload, and not a statement about any control).
_TIER = {"PROVIDED_BUT_CONFLICTING": 0, "EVIDENCE_MISSING": 1,
         "PROVIDED_BUT_INSUFFICIENT": 2, UNREADABLE: 3}
_CSV_HEAD = ("Priority", "Requested document", "Situation", "Questions affected", "Question text",
             "What is needed", "Guidance", "Control areas")


# ------------------------------------------------------------------ knowledge
@lru_cache(maxsize=4)
def _definitions(root: str) -> tuple[dict, dict]:
    """(evidence name -> evidence id, evidence id -> remediation action).

    An evidence type is produced by steps in many remediations, so the step chosen is the one whose
    remediation strengthens the evidence's own controls (primary before supporting), then the one whose
    wording overlaps the evidence name; file order only breaks remaining ties.
    """
    base = Path(root)
    names: dict[str, str] = {}
    words: dict[str, set] = {}
    weights: dict[str, dict[str, int]] = {}
    for p in sorted((base / "evidence").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        names[d["name"]] = d["evidence_id"]
        words[d["evidence_id"]] = {w for w in d["name"].lower().split() if len(w) > 3}
        weights[d["evidence_id"]] = {c["control_id"]: 2 if c.get("necessity") == "primary" else 1
                                     for c in d.get("applicable_controls") or []}
    best: dict[str, tuple[tuple, str]] = {}
    for p in sorted((base / "remediations").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        controls = d.get("strengthens_controls") or []
        title = set(d.get("name", "").lower().split())
        for step in d.get("steps", []):
            action = str(step.get("action", "")).strip().replace(" — ", " - ")
            for ev in step.get("produces_evidence") or []:
                if not action:
                    continue
                score = (max([weights.get(ev, {}).get(c, 0) for c in controls] or [0]),
                         len(words.get(ev, set()) & (title | set(action.lower().split()))))
                if ev not in best or score > best[ev][0]:
                    best[ev] = (score, action)
    return names, {ev: action for ev, (_, action) in best.items()}


def _knowledge_root(root: Optional[Path]) -> str:
    if root:
        return str(root)
    from evaluation.engine import resolve_knowledge_root
    return str(resolve_knowledge_root())


def guidance_for(document: str, root: Optional[Path] = None) -> str:
    try:
        names, guidance = _definitions(_knowledge_root(root))
    except (OSError, ValueError, KeyError):
        return NO_GUIDANCE
    return guidance.get(names.get(document, ""), NO_GUIDANCE)


# ----------------------------------------------------------------------- model
def build_gap_view(areas: Iterable, extraction: Iterable = (), root: Optional[Path] = None) -> dict:
    """Gaps grouped by requested document, priority-ordered, plus per-area sections."""
    areas = list(areas)
    questions = build_question_reports(areas)["questions"]
    groups: dict[str, dict] = {}
    for a, q in zip(areas, questions):
        if q["status"] in ("ESTABLISHED", "NOT_EVALUATED"):
            continue
        docs = list(getattr(a, "evidence_needed", None) or ["Supporting evidence (type not specified)"])
        needs = [m for m in q["missing"] if m != NOTHING_FURTHER and not m.startswith("Evidence of the type:")]
        for doc in docs:
            g = groups.setdefault(doc, dict(document=doc, kinds=set(), questions=[], needs=[]))
            g["kinds"].add(q["gap_kind"])
            g["questions"].append(dict(question_id=q["question_id"], question=q["question"], area=q["area"],
                                       kind=q["gap_kind"], kind_label=GAP_KIND_LABELS[q["gap_kind"]],
                                       status_label=q["status_label"], why=q["why"], missing=q["missing"],
                                       provenance=[dict(filename=f["filename"], locator=f["locator"])
                                                   for f in q["facts_used"]]))
            for n in needs:
                if n not in g["needs"]:
                    g["needs"].append(n)
    ordered = []
    for g in groups.values():
        kind = min(g["kinds"], key=lambda k: _TIER[k])
        ordered.append(dict(document=g["document"], kind=kind, kind_label=GAP_KIND_LABELS[kind],
                            kinds=sorted(g["kinds"], key=lambda k: _TIER[k]),
                            questions=sorted(g["questions"], key=lambda x: x["question_id"]),
                            needs=g["needs"] or ["Document not yet provided." if "EVIDENCE_MISSING" in g["kinds"]
                                 else "Evidence that states what the question asks, with source and period."],
                            guidance=guidance_for(g["document"], root)))
    for g in ordered:
        g["question_count"] = len(g["questions"])
    unreadable = [e for e in (dict(x) if isinstance(x, dict) else x.to_dict() for x in extraction)
                  if e.get("status") not in ("EXTRACTED", "DUPLICATE")]
    for e in unreadable:
        ordered.append(dict(document=e["filename"], kind=UNREADABLE, kind_label=GAP_KIND_LABELS[UNREADABLE],
                            kinds=[UNREADABLE], questions=[], question_count=0,
                            needs=[e.get("detail") or "The file could not be read."],
                            guidance=e.get("remediation") or NO_GUIDANCE))
    ordered.sort(key=lambda g: (_TIER[g["kind"]], -g["question_count"], g["document"]))
    for i, g in enumerate(ordered, 1):
        g["priority"] = i
    by_area: dict[str, list] = {}
    for a, q in zip(areas, questions):
        if q["status"] != "NOT_EVALUATED":
            by_area.setdefault(q["area"], []).append(dict(
                question_id=q["question_id"], question=q["question"], status=q["status"],
                status_label=q["status_label"], kind=q["gap_kind"],
                kind_label=GAP_KIND_LABELS.get(q["gap_kind"], q["status_label"]), why=q["why"],
                missing=q["missing"], remediation=q["remediation"],
                provenance=[dict(filename=f["filename"], locator=f["locator"]) for f in q["facts_used"]]))
    counts = {k: sum(1 for g in ordered if g["kind"] == k) for k in _TIER}
    return dict(groups=ordered, areas=by_area, counts=counts,
                questions_with_gaps=len({x["question_id"] for g in ordered for x in g["questions"]}))


# ------------------------------------------------------------------------- CSV
def _cell(v: str) -> str:
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def gaps_csv(view: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(_CSV_HEAD)
    for g in view["groups"]:
        qs = g["questions"]
        w.writerow([_cell(x) for x in (
            g["priority"], g["document"], g["kind_label"],
            "; ".join(q["question_id"] for q in qs), " | ".join(q["question"] for q in qs),
            "; ".join(g["needs"]), g["guidance"], "; ".join(sorted({q["area"] for q in qs})))])
    return out.getvalue()


# ------------------------------------------------------------------------ HTML
def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _anchor(name: str) -> str:
    return "f-" + "".join(c if c.isalnum() else "-" for c in name)


def _prov(items: list) -> str:
    seen, links = set(), []
    for p in items:
        key = (p["filename"], p["locator"])
        if key not in seen:
            seen.add(key)
            links.append(f"<a href='#{_e(_anchor(p['filename']))}'>{_e(p['filename'])}</a> &middot; {_e(p['locator'])}")
    return "<div class='small'>Source: " + "; ".join(links) + "</div>" if links else ""


def render_strip(view: dict) -> str:
    c = view["counts"]
    cells = [("all", "All gaps", len(view["groups"]))] + [
        (k, GAP_KIND_LABELS[k], c[k]) for k in ("PROVIDED_BUT_CONFLICTING", "EVIDENCE_MISSING",
                                                 "PROVIDED_BUT_INSUFFICIENT", UNREADABLE)]
    return ("<div class='gv-strip nop' role='group' aria-label='Filter by situation'>"
            + "".join(f"<button type='button' data-gv='{k}'><span class='n'>{n}</span>"
                      f"<span class='l'>{_e(l)}</span></button>" for k, l, n in cells) + "</div>")


def render_groups(view: dict) -> str:
    if not view["groups"]:
        return "<div class='card'>No outstanding evidence requests.</div>"
    cards = []
    for g in view["groups"]:
        qs = "".join(
            f"<li data-kind='{q['kind']}'><strong>{_e(q['question_id'])}</strong> {_e(q['question'])}</li>" for q in g["questions"]
        ) or "<li>Not tied to a specific question.</li>"
        cards.append(
            f"<details class='card gv-card gv-group' data-kinds='{' '.join(g['kinds'])}'><summary>"
            f"<span>{g['priority']}. {_e(g['document'])} <span class='small'>&middot; {g['question_count']} question(s)</span></span>"
            f"<span class='tag t-rev'>{_e(g['kind_label'])}</span></summary><div class='gb'>"
            f"<div><strong>What is needed:</strong> {_e('; '.join(g['needs']))}</div>"
            f"<div><strong>Suggested step:</strong> {_e(g['guidance'])}</div>"
            f"<ul>{qs}</ul></div></details>")
    return "".join(cards)


def render_areas(view: dict) -> str:
    out = []
    for area, rows in view["areas"].items():
        items = "".join(
            f"<details class='qrow' id='q-{_e(r['question_id'])}' data-kinds='{r['kind']}'>"
            f"<summary><span><strong>{_e(r['question_id'])}</strong> {_e(r['question'])}</span>"
            f"<span class='tag t-skip'>{_e(r['kind_label'])}</span></summary><div class='qb'>"
            f"<div><strong>Why:</strong> {_e(r['why'])}</div>"
            f"<div class='small'><strong>Still needed:</strong> {_e('; '.join(r['missing']))}</div>"
            f"{_prov(r['provenance'])}</div></details>" for r in rows)
        out.append(f"<h3 class='sec'>{_e(area)} ({len(rows)})</h3>{items}")
    return "".join(out)


_STYLE = ("<style>.gv-strip{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}"
          ".gv-strip button{flex:1;min-width:140px;display:flex;flex-direction:column;align-items:flex-start;gap:2px;"
          "background:var(--card);color:var(--ink);border:1.5px solid var(--line);border-radius:12px;padding:9px 12px;box-shadow:none}"
          ".gv-strip button[aria-pressed=true]{border-color:var(--acc)}.gv-strip .n{font-size:20px;font-weight:700}"
          "[hidden]{display:none!important}</style>")
_FILTER_JS = ("<script>(function(){var s=document.querySelectorAll('[data-gv]');"
              "function go(k){document.querySelectorAll('[data-kinds]').forEach(function(e){"
              "e.hidden=!(k==='all'||e.dataset.kinds.split(' ').indexOf(k)>-1)});"
              "s.forEach(function(b){b.setAttribute('aria-pressed',b.dataset.gv===k)})}"
              "s.forEach(function(b){b.addEventListener('click',function(){go(b.dataset.gv)})})})();</script>")


def render_gap_section(view: dict, assessment_id: str) -> str:
    """Embedded block for the results page: strip, filter, document groups, area sections."""
    aid = _e(assessment_id)
    return (_STYLE + f"<h2>Gaps to close ({len(view['groups'])})</h2>{render_strip(view)}"
            f"<div class='actions nop'><a class='pill' href='/gaps/{aid}'>Evidence request (print view)</a>"
            f"<a class='pill' href='/gaps-csv/{aid}'>Download CSV</a></div>"
            f"{render_groups(view)}<details class='fold'><summary>By control area</summary>{render_areas(view)}</details>{_FILTER_JS}")


def render_request_page(view: dict, vendor: str, assessment_id: str) -> str:
    """Standalone consolidated evidence request, print-friendly."""
    rows = "".join(
        f"<tr><td>{g['priority']}</td><td><strong>{_e(g['document'])}</strong></td><td>{_e(g['kind_label'])}</td>"
        f"<td>{_e(', '.join(q['question_id'] for q in g['questions']) or 'n/a')}</td>"
        f"<td>{_e('; '.join(g['needs']))}</td><td>{_e(g['guidance'])}</td></tr>" for g in view["groups"])
    files = sorted({p["filename"] for rs in view["areas"].values() for r in rs for p in r["provenance"]})
    prov = "".join(f"<li id='{_e(_anchor(f))}'>{_e(f)}</li>" for f in files) or "<li>No source files cited.</li>"
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Evidence request: {_e(vendor)}</title><style>"
            "body{font:14px/1.5 system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1b2430}"
            "h1{font-size:22px;margin:0}table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #cfd6df;padding:6px 8px;text-align:left;vertical-align:top}"
            "th{background:#eef2f6}tr{break-inside:avoid}.small{color:#5b6672;font-size:12px}"
            "@media print{.nop{display:none}body{margin:0}}</style></head><body>"
            f"<h1>Evidence request &mdash; {_e(vendor)}</h1>"
            f"<p class='small'>Assessment {_e(assessment_id)} &middot; {len(view['groups'])} request(s) &middot; "
            f"{view['questions_with_gaps']} question(s) affected. Ordered by priority.</p>"
            "<table><thead><tr><th>#</th><th>Requested document</th><th>Situation</th><th>Questions</th>"
            f"<th>What is needed</th><th>Suggested step</th></tr></thead><tbody>{rows}</tbody></table>"
            f"<h2>Source files cited</h2><ul>{prov}</ul>"
            "<p class='small'>These are readiness observations and requests for material. Missing or unreadable "
            "material says nothing about how a control operates. This is not an audit opinion or certification.</p>"
            f"<p class='nop'><button onclick='window.print()'>Print</button> "
            f"<a href='/gaps-csv/{_e(assessment_id)}'>Download CSV</a> &middot; "
            f"<a href='/doc-results/{_e(assessment_id)}'>Back to results</a></p></body></html>")
