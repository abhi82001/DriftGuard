#!/usr/bin/env python3
"""DriftGuard MVP web app: vendor -> questionnaire -> assessment -> results.

Server-rendered HTML, in-memory state, no database and no authentication.
Run:  uvicorn backend.src.app:app --reload
"""

from __future__ import annotations

import html
import sys
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from assessment import (  # noqa: E402
    STATUS_GAP,
    STATUS_NEEDS_REVIEW,
    STATUS_SKIPPED,
    Assessment,
    MvpKnowledge,
    demo_mode_enabled,
    run_assessment,
)
from documents import (  # noqa: E402
    CLARIFICATION,
    ESTABLISHED,
    NOT_ESTABLISHED,
    PARTIAL,
    DocumentAnalyzer,
    DocumentAssessment,
)
from ingestion import SUPPORTED, extract_many  # noqa: E402

app = FastAPI(title="DriftGuard MVP")

KNOWLEDGE = MvpKnowledge()
ANALYZER = DocumentAnalyzer(KNOWLEDGE)
ASSESSMENTS: dict[str, Assessment] = {}
DOC_ASSESSMENTS: dict[str, DocumentAssessment] = {}

CSS = """
*{box-sizing:border-box}
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#f5f6f8;color:#1d2330}
header{background:#12233b;color:#fff;padding:18px 28px}
header h1{margin:0;font-size:20px}
header p{margin:4px 0 0;font-size:13px;color:#b9c6d8}
main{max-width:1000px;margin:0 auto;padding:24px}
h2{font-size:17px;margin:26px 0 10px}
.card{background:#fff;border:1px solid #dfe3e9;border-radius:6px;padding:16px;margin-bottom:14px}
.cards{display:flex;gap:12px;flex-wrap:wrap}
.cards .card{flex:1;min-width:150px}
.cards .n{font-size:24px;font-weight:600}
.cards .l{font-size:12px;color:#5b6577;text-transform:uppercase}
label{display:block;font-weight:600;font-size:14px;margin-bottom:6px}
input[type=text],textarea,select{width:100%;padding:8px;border:1px solid #c6ccd6;border-radius:4px;font:inherit}
textarea{min-height:64px}
button{background:#12233b;color:#fff;border:0;border-radius:4px;padding:10px 18px;font-size:14px;cursor:pointer}
a{color:#12233b}
.q{border-top:1px solid #eceef2;padding:14px 0}
.q:first-child{border-top:0}
.qid{font-size:12px;color:#6b7383}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;border:1px solid}
.t-gap{background:#fdecec;border-color:#e2a0a0;color:#8c1c1c}
.t-ok{background:#ecf7ee;border-color:#a5cdae;color:#1d5e2c}
.t-rev{background:#fff6e0;border-color:#dcbc73;color:#7a5600}
.t-skip{background:#f0f1f4;border-color:#ccd0d8;color:#5b6577}
.t-mode{background:#e9eefb;border-color:#9fb2e0;color:#26386e}
table{width:100%;border-collapse:collapse;background:#fff;font-size:13px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eceef2;vertical-align:top}
th{background:#f0f2f6;font-size:12px;text-transform:uppercase;color:#5b6577}
.small{font-size:12px;color:#5b6577}
.fnd{margin-top:6px;font-size:12px}
.disclaimer{font-size:12px;color:#5b6577;margin-top:18px}
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        f"<header><h1>DriftGuard</h1><p>SOC 2 CC6/CC7 readiness signals from a "
        f"grounded knowledge base. Not an audit opinion.</p></header>"
        f"<main>{body}</main></body></html>"
    )


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


async def _form(request: Request) -> dict[str, list[str]]:
    """Parse a urlencoded form body without pulling in python-multipart."""
    return parse_qs((await request.body()).decode("utf-8"))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    mode = "DEMO" if demo_mode_enabled() else "CLAUDE"
    types = " ".join(e.lstrip(".").upper() for e in SUPPORTED)
    return _page("DriftGuard", f"""
<div class="card">
  <h2 style="margin-top:0">SOC 2 Readiness Assessment</h2>
  <p class="small">Readiness review of CC6/CC7 from your existing security
  documentation. Material is analysed only against DriftGuard's knowledge base;
  nothing here is a compliance conclusion.</p>
  <p><span class="tag t-mode">MODE: {mode}</span></p>
  <form method="post" action="/analyze" enctype="multipart/form-data">
    <label for="vendor">Company</label>
    <input type="text" id="vendor" name="vendor" required placeholder="Acme Cloud Inc.">
    <p><label for="files">Upload security material</label>
    <input type="file" id="files" name="files" multiple
           accept="{','.join(SUPPORTED)}"></p>
    <p class="small">{types} &middot; max 10 files, 5 MB each</p>
    <p><button type="submit">Analyze Documents</button></p>
  </form>
</div>
<p class="small" style="text-align:center">&mdash;&mdash;&mdash;&mdash; OR &mdash;&mdash;&mdash;&mdash;</p>
<div class="card">
  <form method="post" action="/assessment">
    <label for="mvendor">Answer the full questionnaire instead</label>
    <input type="text" id="mvendor" name="vendor" required placeholder="Acme Cloud Inc.">
    <p><button type="submit">Start Manual Assessment</button></p>
  </form>
</div>""")


@app.post("/analyze")
async def analyze(request: Request):
    form = await request.form()
    vendor = str(form.get("vendor") or "Unnamed vendor")
    uploads = form.getlist("files")
    payloads = []
    for upload in uploads:
        filename = getattr(upload, "filename", "") or ""
        if not filename:
            continue
        payloads.append((filename, await upload.read()))

    documents, errors = extract_many(payloads)
    if not payloads:
        errors.append("no files were uploaded")
    result = ANALYZER.analyze(vendor, documents, errors, demo_mode_enabled())
    DOC_ASSESSMENTS[result.assessment_id] = result
    return RedirectResponse(f"/doc-results/{result.assessment_id}", status_code=303)


@app.get("/doc-results/{assessment_id}", response_class=HTMLResponse)
def doc_results(assessment_id: str) -> HTMLResponse:
    a = DOC_ASSESSMENTS.get(assessment_id)
    if a is None:
        return _page("Not found", "<div class='card'>Unknown assessment. "
                                  "<a href='/'>Start again</a>.</div>")
    cards = "".join(
        f"<div class='card'><div class='n'>{v}</div><div class='l'>{k.replace('_',' ')}</div></div>"
        for k, v in a.counts.items()
    )
    tags = {ESTABLISHED: "t-ok", PARTIAL: "t-rev", NOT_ESTABLISHED: "t-skip",
            CLARIFICATION: "t-gap"}

    def section(status: str, title: str) -> str:
        rows = [x for x in a.areas if x.status == status]
        if not rows:
            return ""
        body = "".join(
            f"<tr><td>{_esc(x.area)}<div class='small'>{_esc(x.question)}</div></td>"
            f"<td><span class='tag {tags[x.status]}'>{_esc(x.status.replace('_',' '))}</span></td>"
            f"<td>{_esc(x.reason)}"
            + ("".join(
                f"<div class='fnd'>known fact: {_esc(f.statement)}"
                f"<div class='small'>source: {_esc(f.source_file)} &middot; "
                f"{_esc(f.source_locator)} ({_esc(f.nature)})</div>"
                f"<div class='small'>&ldquo;{_esc(f.snippet[:160])}&rdquo;</div></div>"
                for f in x.known_facts) or "")
            + "</td>"
            f"<td class='small'>{_esc('; '.join(x.missing_facts)) or '&mdash;'}</td>"
            f"<td class='small'>{_esc('; '.join(x.evidence_needed)) or '&mdash;'}"
            f"<details><summary class='small'>details</summary>"
            f"<span class='small'>{_esc(', '.join(x.detail_ids + [x.question_id]))}</span>"
            f"</details></td></tr>"
            for x in rows
        )
        return (f"<h2>{title} ({len(rows)})</h2><table><tr><th>Area</th><th>Status</th>"
                f"<th>Explanation / known facts</th><th>Still unknown</th>"
                f"<th>Evidence still needed</th></tr>{body}</table>")

    follow = a.follow_ups()
    follow_form = ""
    if follow:
        requests = "".join(
            f"<div class='q'><div class='qid'>{_esc(x.area)} &middot; evidence request</div>"
            f"<div>{_esc(x.prompt)}</div></div>"
            for x in follow if x.kind == "evidence_request"
        )
        fields = []
        for x in [y for y in follow if y.kind == "question"]:
            question = KNOWLEDGE.question(x.questionnaire_id, x.question_id)
            name = f"{x.questionnaire_id}|{x.question_id}"
            if question["answer_type"] == "single_select":
                opts = "".join(f"<option value='{_esc(o)}'>{_esc(o)}</option>"
                               for o in question["options"])
                control = (f"<select name='{name}'><option value=''>-- no answer --</option>"
                           f"{opts}</select>")
            elif question["answer_type"] == "multi_select":
                control = "".join(
                    f"<div><label class='small' style='font-weight:400'>"
                    f"<input type='checkbox' name='{name}' value='{_esc(o)}'> {_esc(o)}"
                    f"</label></div>" for o in question["options"])
            else:
                control = f"<textarea name='{name}'></textarea>"
            fields.append(
                f"<div class='q'><div class='qid'>{_esc(x.area)} &middot; "
                f"{_esc(x.status.replace('_',' '))}</div>"
                f"<label>{_esc(x.prompt)}</label>"
                f"<div class='small'>why asked: {_esc(x.reason)}</div>{control}</div>"
            )
        form_block = ""
        if fields:
            form_block = (
                f"<form method='post' action='/clarify/{_esc(a.assessment_id)}'>"
                f"{''.join(fields)}"
                f"<p><button type='submit'>Submit answers</button></p></form>"
            )
        follow_form = f"""
<h2>DriftGuard needs clarification</h2>
<div class="card"><p class="small">Only what your material did not settle is shown.</p>
{requests}{form_block}</div>"""

    errors = ""
    if a.errors:
        errors = ("<div class='card'><strong>Files not analysed</strong>"
                  + "".join(f"<div class='small'>{_esc(e)}</div>" for e in a.errors)
                  + "</div>")
    mode_note = ""
    if a.mode == "DEMO":
        mode_note = ("<div class='card'><span class='tag t-mode'>DEMO</span> "
                     "Document analysis is local deterministic keyword matching "
                     "against DriftGuard's evidence expectations - not model "
                     "analysis - and no external call was made.</div>")

    return _page(f"DriftGuard results: {a.vendor}", f"""
<div class="card"><h2 style="margin-top:0">Vendor: {_esc(a.vendor)}</h2>
<span class="tag t-mode">MODE: {_esc(a.mode)}</span>
<div class="small">documents: {_esc(', '.join(a.documents)) or 'none'}</div></div>
{mode_note}{errors}
<div class="cards">{cards}</div>
{section(ESTABLISHED, "Established")}
{section(PARTIAL, "Partially established")}
{section(CLARIFICATION, "Clarification required")}
{section(NOT_ESTABLISHED, "Not evidenced by supplied material")}
{follow_form}
<p class="disclaimer">DriftGuard produces readiness signals only. Missing material
is not a control failure, and a policy statement is not evidence of operating
effectiveness. Nothing here is a SOC 2 compliance conclusion, audit opinion, or
certification.</p>
<p><a href="/assessment?vendor={_esc(a.vendor)}">Answer full questionnaire manually</a>
&middot; <a href="/">Start over</a></p>""")


@app.post("/clarify/{assessment_id}")
async def clarify(assessment_id: str, request: Request):
    a = DOC_ASSESSMENTS.get(assessment_id)
    vendor = a.vendor if a else "Unnamed vendor"
    form = await _form(request)
    answers: dict[tuple[str, str], object] = {}
    for key, raw in form.items():
        if "|" not in key:
            continue
        qn_id, q_id = key.split("|", 1)
        values = [v for v in raw if v.strip()]
        if not values:
            continue
        question = KNOWLEDGE.question(qn_id, q_id)
        answers[(qn_id, q_id)] = (
            values if question["answer_type"] == "multi_select" else values[0]
        )
    result = run_assessment(KNOWLEDGE, vendor, answers)
    ASSESSMENTS[result.assessment_id] = result
    return RedirectResponse(f"/results/{result.assessment_id}", status_code=303)


def _question_form(vendor: str) -> HTMLResponse:
    blocks = []
    for doc in KNOWLEDGE.questionnaires:
        qn_id = doc["questionnaire_id"]
        rows = []
        for q in doc["questions"]:
            name = f"{qn_id}|{q['question_id']}"
            if q["answer_type"] == "single_select":
                opts = "".join(
                    f"<option value='{_esc(o)}'>{_esc(o)}</option>" for o in q["options"]
                )
                control = f"<select name='{name}'><option value=''>-- no answer --</option>{opts}</select>"
            elif q["answer_type"] == "multi_select":
                control = "".join(
                    f"<div><label class='small' style='font-weight:400'>"
                    f"<input type='checkbox' name='{name}' value='{_esc(o)}'> {_esc(o)}</label></div>"
                    for o in q["options"]
                )
            else:
                control = f"<textarea name='{name}' placeholder='Free-text answer'></textarea>"
            rows.append(
                f"<div class='q'><div class='qid'>{_esc(q['question_id'])} &middot; "
                f"{_esc(q['answer_type'])}</div><label>{_esc(q['text'])}</label>{control}</div>"
            )
        blocks.append(
            f"<h2>{_esc(qn_id)} &mdash; {_esc(doc['name'])} "
            f"<span class='small'>({', '.join(doc['covers_criteria'])})</span></h2>"
            f"<div class='card'>{''.join(rows)}</div>"
        )
    return _page("DriftGuard assessment", f"""
<div class="card"><strong>Vendor:</strong> {_esc(vendor)}
<span class="tag t-mode">MODE: {'DEMO' if demo_mode_enabled() else 'CLAUDE'}</span>
<p class="small">Leave a question blank to skip it.</p></div>
<form method="post" action="/run">
  <input type="hidden" name="vendor" value="{_esc(vendor)}">
  {''.join(blocks)}
  <p><button type="submit">Run Assessment</button></p>
</form>""")


@app.get("/assessment", response_class=HTMLResponse)
def assessment_get(vendor: str = "Demo Vendor") -> HTMLResponse:
    return _question_form(vendor)


@app.post("/assessment", response_class=HTMLResponse)
async def assessment_post(request: Request) -> HTMLResponse:
    form = await _form(request)
    return _question_form((form.get("vendor") or ["Unnamed vendor"])[0])


@app.post("/run")
async def run(request: Request):
    form = await _form(request)
    vendor = (form.get("vendor") or ["Unnamed vendor"])[0]
    answers: dict[tuple[str, str], object] = {}
    for key, raw in form.items():
        if key == "vendor" or "|" not in key:
            continue
        qn_id, q_id = key.split("|", 1)
        values = [v for v in raw if v.strip()]
        if not values:
            continue
        question = KNOWLEDGE.question(qn_id, q_id)
        answers[(qn_id, q_id)] = (
            values if question["answer_type"] == "multi_select" else values[0]
        )

    result = run_assessment(KNOWLEDGE, vendor, answers)
    ASSESSMENTS[result.assessment_id] = result
    return RedirectResponse(f"/results/{result.assessment_id}", status_code=303)


@app.get("/results/{assessment_id}", response_class=HTMLResponse)
def results(assessment_id: str) -> HTMLResponse:
    a = ASSESSMENTS.get(assessment_id)
    if a is None:
        return _page("Not found", "<div class='card'>Unknown assessment. "
                                  "<a href='/'>Start again</a>.</div>")
    c = a.counts
    cards = "".join(
        f"<div class='card'><div class='n'>{v}</div><div class='l'>{k.replace('_',' ')}</div></div>"
        for k, v in c.items()
    )

    rows = []
    for r in a.results:
        if r.status == STATUS_SKIPPED:
            continue
        tag = {
            STATUS_GAP: "<span class='tag t-gap'>GAP SIGNAL</span>",
            STATUS_NEEDS_REVIEW: "<span class='tag t-rev'>NEEDS REVIEW</span>",
        }.get(r.status, "<span class='tag t-ok'>NO GAP SIGNAL</span>")
        if r.needs_review and r.status != STATUS_NEEDS_REVIEW:
            tag += " <span class='tag t-rev'>NEEDS REVIEW</span>"

        semantic = "&mdash;"
        if r.verdict:
            semantic = (
                f"<strong>{_esc(r.verdict)}</strong><br><span class='small'>"
                f"confidence {r.confidence} &middot; {_esc(', '.join(r.reason_codes))}"
                f"<br>source: {_esc(r.source)}</span>"
            )

        findings = "&mdash;"
        if r.findings:
            findings = "".join(
                f"<div class='fnd'><strong>{_esc(f['finding_id'])}</strong> "
                f"({_esc(f['severity'])}) {_esc(f['name'])}"
                f"<br><span class='small'>{_esc(f['description'])}</span>"
                f"<br><span class='small'>signal: {_esc(f.get('condition',''))}</span>"
                + ("".join(
                    f"<br><span class='small'>remediation: {_esc(m['remediation_id'])} "
                    f"&mdash; {_esc(m['name'])} (effort: {_esc(m['effort'])})</span>"
                    for m in f["remediations"]) or
                   "<br><span class='small'>no mapped remediation</span>")
                + "</div>"
                for f in r.findings
            )

        answer = r.answer if isinstance(r.answer, str) else ", ".join(r.answer or [])
        rows.append(
            f"<tr><td><div class='qid'>{_esc(r.question_id)}</div>{_esc(r.text)}"
            f"<div class='small'>answer: {_esc(answer[:240])}</div></td>"
            f"<td>{_esc(r.mode)}</td><td>{tag}<div class='small'>{_esc(r.detail)}</div></td>"
            f"<td>{semantic}</td><td>{findings}</td></tr>"
        )

    demo_note = ""
    if a.mode == "DEMO":
        demo_note = ("<div class='card'><span class='tag t-mode'>DEMO</span> "
                     "Semantic results on this page were produced by a local "
                     "deterministic stub, not by any model, and no external call "
                     "was made.</div>")

    return _page(f"DriftGuard results: {a.vendor}", f"""
<div class="card"><h2 style="margin-top:0">Results &mdash; {_esc(a.vendor)}</h2>
<span class="tag t-mode">MODE: {_esc(a.mode)}</span>
<span class="small">assessment {_esc(a.assessment_id)}</span></div>
{demo_note}
<div class="cards">{cards}</div>
<h2>Evaluated questions</h2>
<table><tr><th>Question</th><th>Mode</th><th>Status</th><th>Semantic verdict</th>
<th>Observation / remediation</th></tr>{''.join(rows) or
  "<tr><td colspan='5'>No questions were answered.</td></tr>"}</table>
<p class="disclaimer">DriftGuard produces readiness signals only. Nothing here is a
SOC 2 compliance conclusion, audit opinion, or certification. Items marked NEEDS
REVIEW require human judgement.</p>
<p><a href="/">Start another assessment</a></p>""")
