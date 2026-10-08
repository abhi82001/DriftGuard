#!/usr/bin/env python3
"""DriftGuard MVP web app: vendor -> questionnaire -> assessment -> results.

Server-rendered HTML MVP with bounded in-memory active state plus local SQLite account/session persistence.
Run:  uvicorn backend.src.app:app --reload
"""

from __future__ import annotations

import html
import logging
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    CONFLICT,
    NOT_EVALUATED,
    ESTABLISHED,
    NOT_ESTABLISHED,
    PARTIAL,
    DocumentAnalyzer,
    DocumentAssessment,
)
from evidence import (  # noqa: E402
    NO_EXCEPTIONS,
    analyze_evidence,
    build_report,
    fact_display,
)
from ingestion import SUPPORTED, extract_many, extract_many_detailed  # noqa: E402
from evidence.backbone import analyze_artifacts  # noqa: E402
from evidence.mapping import map_questionnaire  # noqa: E402
from evidence.intelligence import build_intelligence  # noqa: E402
from upload_security import authorize_api, read_uploads, MAX_TOTAL_BYTES  # noqa: E402
from semantic_extraction import configured_provider, SEMANTIC_ACTIVE  # noqa: E402
from narrative_claims import HybridGroundedExtractor  # noqa: E402
from production_hardening import BoundedAssessmentStore, safe_event  # noqa: E402
from observability import (  # noqa: E402
    ErrorCode, assessment_id_from_path, assessment_id_var, code_for_status, log_event,
    new_request_id, request_id_var, configure as _configure_logging,
)
from upload_store import UploadStore  # noqa: E402
import jobs as _jobs  # noqa: E402

app = FastAPI(title="DriftGuard MVP")
_configure_logging()

KNOWLEDGE = MvpKnowledge()
_SEMANTIC_PROVIDER, _SEMANTIC_STATUS = configured_provider()
ANALYZER = DocumentAnalyzer(KNOWLEDGE, extractor=HybridGroundedExtractor(_SEMANTIC_PROVIDER))
ASSESSMENTS = BoundedAssessmentStore()
DOC_ASSESSMENTS = BoundedAssessmentStore()
_ASSESSMENT_OWNERS: dict[tuple[str, str], str] = {}
UPLOADS = UploadStore()
_GUEST_COOKIE = 'driftguard_guest'
_GUEST_MAX_FILES = 3
_GUEST_MAX_TOTAL_BYTES = 10 * 1024 * 1024
_GUEST_MAX_FILE_BYTES = 5 * 1024 * 1024


def _mode_label() -> str:
    """DEMO (stub), CLAUDE / AI (provider ready) or RULES-ONLY (AI off; deterministic checks still run)."""
    if demo_mode_enabled():
        return "DEMO"
    if _SEMANTIC_STATUS != SEMANTIC_ACTIVE:
        return "RULES-ONLY"
    return "CLAUDE" if getattr(_SEMANTIC_PROVIDER, "provider", "anthropic") == "anthropic" else "AI"


def _ai_health() -> dict:
    """AI readiness without any network call. Never exposes the key."""
    from driftguard_platform.ai_runtime import readiness
    r = readiness()
    return {"mode": _mode_label(), "semantic_status": _SEMANTIC_STATUS,
            "ai_active": _SEMANTIC_STATUS == SEMANTIC_ACTIVE,
            "provider": r["provider"], "model": r["model"],
            "missing_config": [] if demo_mode_enabled() else r["missing"],
            "reason": r["reason"],
            "deprecated_env_in_use": r["deprecated_env_in_use"],
            "note": "AI is optional; without it all deterministic checks still run and semantic items show NEEDS_REVIEW."}


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "ai": _ai_health()})


def _wants_html(request: Request) -> bool:
    return not request.url.path.startswith("/api") and "text/html" in request.headers.get("accept", "text/html")


def _error_response(request: Request, status: int, message: str):
    if _wants_html(request):
        return _page("Something went wrong",
                     f"<div class='card'><h2>Something went wrong</h2><p>{_esc(message)}</p>"
                     "<a class='pill' href='/'>Back to start</a></div>", status)
    return JSONResponse({"error": message}, status_code=status)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code in (301, 302, 303, 307, 308):
        return Response(status_code=exc.status_code, headers=exc.headers)
    log_event("http_error", code=code_for_status(exc.status_code), level=logging.WARNING, status=exc.status_code,
              method=request.method, path=request.url.path)
    return _error_response(request, exc.status_code, str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception):
    log_event("unhandled_error", code=ErrorCode.INTERNAL, level=logging.ERROR, method=request.method,
              path=request.url.path, error_type=type(exc).__name__)   # class only: messages can embed evidence
    return _error_response(request, 500, "Unexpected error. Your data was not changed; please retry. "
                                         "If it persists, check the server log.")


def _guest_error(msg: str, code: int) -> HTMLResponse:
    return _page('Guest demo', f"<div class='card'><h2>Guest demo</h2><p>{_esc(msg)}</p><a class='pill' href='/guest'>Back</a></div>", code)

CSS = """
:root{--bg:#f5f7fa;--card:#fff;--ink:#14213d;--mut:#5b6678;--line:#dfe4ec;--acc:#2456d6;--acc2:#2456d6;--acc-ink:#fff;--soft:#eef2f8;
--ok:#14935a;--par:#c47f00;--clr:#2a6fdb;--con:#d6384a;--na:#7b8494;--r:12px;
--sh:0 1px 2px rgba(20,33,61,.06),0 4px 12px rgba(20,33,61,.04);--grad:var(--acc)}
@media (prefers-color-scheme:dark){:root{--bg:#0e131d;--card:#161d2b;--ink:#e6eaf2;--mut:#9aa6bb;--line:#273044;--acc:#6b9bff;--acc2:#6b9bff;--acc-ink:#0e131d;--soft:#1d2636;
--ok:#4cc380;--par:#e6b23a;--clr:#6aa2ff;--con:#ff6b7d;--na:#98a2bb;--sh:0 1px 2px rgba(0,0,0,.4),0 10px 28px rgba(0,0,0,.25)}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;margin:0;color:var(--ink);line-height:1.5;
background:var(--bg)}
header{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;padding:12px clamp(14px,4vw,32px);
background:color-mix(in srgb,var(--card) 80%,transparent);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
header .logo{width:34px;height:34px;border-radius:8px;background:var(--grad);display:grid;place-items:center;flex:none}
header .logo svg{width:20px;height:20px}
header h1{margin:0;font-size:18px;letter-spacing:-.02em;line-height:1.1}
header p{margin:2px 0 0;font-size:12px;color:var(--mut)}
header .sp{flex:1}
.hnav{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end;font-size:13.5px;font-weight:600}
.hnav a{padding:7px 12px;border-radius:999px;color:var(--ink);text-decoration:none;white-space:nowrap;transition:background .15s,color .15s}
.hnav a:hover{background:var(--soft);color:var(--acc)}
.hnav a.cta{background:var(--grad);color:var(--acc-ink)}
.hnav a.cta:hover{filter:brightness(1.07);color:#fff}
.hnav form{margin:0}.hnav button{padding:7px 14px;font-size:13.5px;border-radius:999px}
.hnav .gchip{display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border-radius:999px;background:var(--soft);border:1px solid var(--line);color:var(--mut);font-size:12.5px;white-space:nowrap}
.hnav .gchip::before{content:'';width:7px;height:7px;border-radius:50%;background:#f59e0b;box-shadow:0 0 0 3px color-mix(in srgb,#f59e0b 25%,transparent)}
.hnav .vr{width:1px;height:20px;background:var(--line);margin:0 4px}
header .sp{min-width:0}@media (max-width:1000px){header a.brand p{display:none}header{gap:10px}.hnav .vr{display:none}}
@media (max-width:560px){.hnav a:not(.cta){padding:7px 9px}.hnav .gchip{font-size:11.5px;padding:5px 9px}header .t-mode{display:none}}
header a.brand{display:flex;gap:12px;align-items:center;text-decoration:none;color:inherit}
main{max-width:1120px;margin:0 auto;padding:22px clamp(12px,3vw,24px) 56px}
h2{font-size:17px;margin:26px 0 10px;letter-spacing:-.01em}
h3{margin:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;margin-bottom:14px;box-shadow:var(--sh)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
.cards .card{margin:0}
.cards .n{font-size:26px;font-weight:700;letter-spacing:-.02em}
.cards .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
label{display:block;font-weight:600;font-size:14px;margin-bottom:6px}
input[type=text],textarea,select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font:inherit;background:var(--card);color:var(--ink);transition:border-color .15s,box-shadow .15s}
input[type=text]:focus,textarea:focus,select:focus{outline:0;border-color:var(--acc);box-shadow:0 0 0 4px color-mix(in srgb,var(--acc) 18%,transparent)}
button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
textarea{min-height:110px;resize:vertical}
button{background:var(--grad);color:var(--acc-ink);border:0;border-radius:8px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer;transition:filter .15s}
button:hover{filter:brightness(1.08)}
button:active{transform:none}
button:disabled{opacity:.4;cursor:default;transform:none;filter:none}
button.ghost{background:var(--card);color:var(--ink);border:1.5px solid var(--line);box-shadow:none}
a{color:var(--acc)}
.pill{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border:1.5px solid var(--line);border-radius:999px;background:var(--card);color:var(--ink);text-decoration:none;font-size:13px;font-weight:600}
.pill:hover{border-color:var(--acc);color:var(--acc)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
.q{border-top:1px solid var(--line);padding:14px 0}
.q:first-child{border-top:0}
.qid{font-size:12px;color:var(--mut)}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px;border:1px solid;white-space:nowrap}
.t-gap{background:color-mix(in srgb,var(--con) 12%,transparent);border-color:var(--con);color:var(--con)}
.t-ok{background:color-mix(in srgb,var(--ok) 12%,transparent);border-color:var(--ok);color:var(--ok)}
.t-rev{background:color-mix(in srgb,var(--par) 14%,transparent);border-color:var(--par);color:var(--par)}
.t-skip{background:var(--soft);border-color:var(--line);color:var(--mut)}
.t-mode{background:color-mix(in srgb,var(--acc) 12%,transparent);border-color:var(--acc);color:var(--acc)}
table{width:100%;border-collapse:collapse;background:var(--card);font-size:13px;display:block;overflow-x:auto;border-radius:12px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--soft);font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
.small{font-size:12px;color:var(--mut)}
.fnd{margin-top:6px;font-size:12px}
.disclaimer{font-size:12px;color:var(--mut);margin-top:18px}
/* landing */
.hero{text-align:center;padding:26px 8px 22px;max-width:760px;margin:0 auto}
.hero h2{font-size:clamp(26px,5vw,40px);line-height:1.12;letter-spacing:-.03em;margin:10px 0}
.hero h2 em{font-style:normal;color:var(--acc)}
.hero p{color:var(--mut);margin:0 auto;max-width:600px}
.steps3{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:16px}
.steps3 span{font-size:12px;font-weight:600;padding:6px 12px;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--mut)}
.steps3 b{color:var(--acc);margin-right:4px}
.choices{display:grid;grid-template-columns:1.35fr 1fr;gap:16px;align-items:stretch}
.choice{display:flex;flex-direction:column;margin:0;padding:22px}
.choice.main{border-color:color-mix(in srgb,var(--acc) 45%,var(--line));box-shadow:0 0 0 4px color-mix(in srgb,var(--acc) 8%,transparent),var(--sh)}
.choice h3{font-size:18px;display:flex;gap:10px;align-items:center;margin-bottom:6px}
.choice h3 i{font-style:normal;width:34px;height:34px;border-radius:10px;display:grid;place-items:center;background:color-mix(in srgb,var(--acc) 14%,transparent)}
.choice form{display:flex;flex-direction:column;gap:12px;flex:1;margin-top:8px}
.choice .grow{flex:1}
.drop{display:block;position:relative;border:2px dashed var(--line);border-radius:14px;padding:22px 14px;text-align:center;background:var(--soft);transition:.15s}
.drop:hover,.drop.over{border-color:var(--acc);background:color-mix(in srgb,var(--acc) 8%,var(--soft))}
.drop input[type=file]{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}
.drop b{display:block;font-size:15px}
#filelist{margin-top:8px;max-height:220px;overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--soft)}
#filelist:empty{display:none}
.frow{display:flex;align-items:center;gap:10px;padding:6px 10px;font-size:13px;border-bottom:1px solid var(--line)}
.frow .fname{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.frow .fsize{color:var(--muted,#667);white-space:nowrap;font-size:12px}
.frow.bad .fsize,.fwarn{color:#c0392b}
.fx,.fmore{border:0;background:none;cursor:pointer;color:inherit;font:inherit;box-shadow:none}
.fx{padding:2px 6px;opacity:.6}.fx:hover{opacity:1}
.fmore{display:block;width:100%;padding:6px;font-size:13px;color:var(--acc)}
.fwarn{padding:6px 10px;font-size:12px}
.drop svg{width:30px;height:30px;color:var(--acc);margin-bottom:4px}
.btn-main{width:100%}
/* tabs */
.tabs{position:sticky;top:61px;z-index:15;display:flex;gap:6px;overflow-x:auto;padding:8px;margin:0 0 16px;border-radius:14px;background:color-mix(in srgb,var(--card) 88%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid var(--line);box-shadow:var(--sh);scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs button{flex:none;display:flex;gap:8px;align-items:center;background:transparent;color:var(--mut);box-shadow:none;padding:9px 16px;font-size:14px;border-radius:10px}
.tabs button:hover{background:var(--soft);transform:none;filter:none;color:var(--ink)}
.tabs button.on{background:var(--grad);color:var(--acc-ink)}
.tabs .bd{font-size:11px;min-width:20px;padding:1px 6px;border-radius:999px;background:color-mix(in srgb,currentColor 18%,transparent);text-align:center}
.tabpanel{scroll-margin-top:130px}
html.js .tabpanel{display:none}
html.js .tabpanel.on{display:block;animation:rise .25s ease}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
/* results */
.top{display:flex;gap:22px;align-items:center;flex-wrap:wrap;}
.top h2{margin:0;font-size:22px;letter-spacing:-.02em}
.top .meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.gauge{width:112px;height:112px;flex:none}
.gauge text{fill:var(--ink);font-weight:700}
.gauge .arc{animation:arc 1s ease-out}
@keyframes arc{from{stroke-dasharray:0 100}}
.dist{display:flex;height:14px;border-radius:999px;overflow:hidden;background:var(--soft);margin:10px 0 12px}
.dist i{display:block;background:var(--c);transition:flex .4s}
.legend{display:flex;gap:8px;flex-wrap:wrap}
.legend button,.strip button{background:var(--card);color:var(--ink);border:1.5px solid var(--line);border-radius:12px;padding:9px 12px;text-align:left;box-shadow:none;display:flex;gap:10px;align-items:center;flex:1;min-width:140px}
.legend button:hover,.strip button:hover{border-color:var(--c);transform:none}
.legend .dot{width:10px;height:10px;border-radius:50%;background:var(--c);flex:none}
.legend .n,.strip .n{font-size:20px;font-weight:700;color:var(--c);line-height:1}
.legend .l,.strip .l{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--mut)}
.strip{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
.strip button{flex-direction:column;align-items:flex-start;gap:4px;border-bottom:4px solid var(--c)}
.strip button .n{font-size:26px}
.strip button.on{background:color-mix(in srgb,var(--c) 10%,var(--card));border-color:var(--c)}
.s-ESTABLISHED{--c:var(--ok)}.s-PARTIALLY_ESTABLISHED{--c:var(--par)}.s-CLARIFICATION_REQUIRED{--c:var(--clr)}.s-CONFLICT{--c:var(--con)}.s-NOT_ESTABLISHED{--c:var(--na)}
details.qrow{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--c,var(--na));border-radius:14px;margin-bottom:8px;box-shadow:var(--sh)}
details.qrow>summary{cursor:pointer;padding:12px 14px;display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
details.qrow .qb{padding:0 14px 14px;border-top:1px solid var(--line)}
details.qrow .qb>div{margin-top:8px}
.alert{border-left:6px solid var(--con);background:color-mix(in srgb,var(--con) 8%,var(--card))}
.alert strong{color:var(--con)}
details.fold{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:10px 0;padding:2px 16px}
details.fold>summary{cursor:pointer;font-weight:600;padding:12px 0}
.kf{display:grid;grid-template-columns:1fr 1fr;gap:14px;background:transparent;border:0;box-shadow:none;padding:0}
.kf>div{padding:14px 16px;border-radius:14px;border:1px solid var(--line);border-top:5px solid var(--c);background:var(--card);box-shadow:var(--sh)}
.kf ul{margin:8px 0 0;padding-left:18px}
.kf li{margin-bottom:4px}
.kf-ok{--c:var(--ok)}
.kf-bad{--c:var(--con)}
.kf-ok strong{color:var(--ok)}.kf-bad strong{color:var(--con)}
table.gaps{display:table;table-layout:fixed}
table.gaps tr{border-left:6px solid var(--c)}
table.gaps th:nth-child(1){width:18%}table.gaps th:nth-child(2){width:14%}
table.gaps td{overflow-wrap:anywhere}
.qwrap{max-height:none}
/* wizard */
.wz-top{margin-bottom:14px}
.wz-bar{height:8px;border-radius:999px;background:var(--soft);overflow:hidden}
.wz-bar i{display:block;height:100%;width:0;background:var(--grad);border-radius:999px;transition:width .3s}
.wz-meta{display:flex;justify-content:space-between;gap:10px;margin-top:8px;font-size:12px;color:var(--mut);font-weight:600}
.wz-group{color:var(--acc);text-align:right}
html.js .wizard .step{display:none}
html.js .wizard .step.on{display:block;animation:rise .25s ease}
.step{padding:6px 0}
.qtext{font-size:clamp(18px,3.4vw,22px);line-height:1.3;letter-spacing:-.015em;margin:6px 0 16px}
.why{font-size:12px;color:var(--mut);margin:-8px 0 14px}
.opts{display:grid;gap:8px}
.opt{position:relative;display:flex;gap:12px;align-items:flex-start;padding:13px 14px;border:1.5px solid var(--line);border-radius:14px;cursor:pointer;margin:0;font-weight:500;background:var(--card);transition:border-color .12s,background .12s}
.opt:hover{border-color:color-mix(in srgb,var(--acc) 55%,var(--line))}
.opt input{position:absolute;opacity:0;pointer-events:none}
.opt .mk{width:20px;height:20px;border-radius:50%;border:2px solid var(--line);flex:none;margin-top:1px;display:grid;place-items:center;transition:.12s}
.opt .mk.sq{border-radius:6px}
.opt:has(input:checked){border-color:var(--acc);background:color-mix(in srgb,var(--acc) 9%,var(--card))}
.opt:has(input:checked) .mk{border-color:var(--acc);background:var(--acc);box-shadow:inset 0 0 0 3px var(--card)}
.opt:has(input:checked) .mk.sq{box-shadow:none}
.opt:has(input:checked) .mk.sq:after{content:"";width:5px;height:10px;border:solid var(--acc-ink);border-width:0 2px 2px 0;transform:rotate(45deg) translate(-1px,-1px)}
.opt:has(input:focus-visible){outline:2px solid var(--acc);outline-offset:2px}
.hint{font-size:12px;color:var(--mut);margin:-6px 0 10px}
.wz-nav{display:flex;gap:10px;align-items:center;justify-content:space-between;margin-top:20px;padding-top:16px;border-top:1px solid var(--line);flex-wrap:wrap}
.wz-nav .mid{font-size:12px;color:var(--mut);flex:1;text-align:center}
.wz-nav [hidden]{display:none}
@media (max-width:760px){
.choices,.kf{grid-template-columns:1fr}
header p{display:none}
.tabs{top:61px;gap:4px;padding:6px;scroll-snap-type:x proximity}
.tabs button{padding:8px 10px;font-size:13px;gap:5px;scroll-snap-align:start}
.top{gap:14px}
.gauge{width:88px;height:88px}
.wz-nav .mid{order:3;flex-basis:100%}
.wz-nav button{flex:1 1 40%;padding:12px 10px;white-space:nowrap}
.wz-nav .wz-submit{flex-basis:100%;order:4}
.wz-nav{position:sticky;bottom:0;background:var(--card);padding-bottom:12px;margin-bottom:-6px}
table.gaps,table.gaps thead,table.gaps tbody,table.gaps tr,table.gaps td{display:block;width:auto!important}
table.gaps thead{display:none}
table.gaps tr{margin:10px 0;border:1px solid var(--line);border-left:6px solid var(--c);border-radius:12px;padding:8px 12px}
table.gaps td{border:0;padding:4px 0}
table.gaps td:before{content:attr(data-l);display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
table.rt,table.rt thead,table.rt tbody,table.rt tr,table.rt td{display:block;width:auto}
table.rt thead{display:none}
table.rt tr{margin:10px 0;border:1px solid var(--line);border-radius:12px;padding:8px 12px;background:var(--card)}
table.rt td{border:0;padding:4px 0}
table.rt td:before{content:attr(data-l);display:block;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
}

/* my assessments */
.pg-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin:4px 0 14px}
.pg-head h2{margin:0;font-size:22px}.pg-head p{margin:2px 0 0;color:var(--mut);font-size:13px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:10px;margin-bottom:12px}
.toolbar input,.toolbar select{width:auto;flex:1 1 140px;min-width:120px;padding:8px 10px;font-size:13px}
.toolbar input[type=text],.toolbar input[name=q]{flex:2 1 200px}
.toolbar button{padding:8px 16px}
.alist{list-style:none;margin:0;padding:0}
.arow{display:grid;grid-template-columns:auto 1fr auto auto;gap:6px 14px;align-items:center;padding:12px 16px;border-top:1px solid var(--line)}
.arow:first-child{border-top:0}.arow:hover{background:var(--soft)}
.arow .nm{font-weight:600;text-decoration:none;color:var(--ink);overflow-wrap:anywhere}.arow .nm:hover{color:var(--acc)}
.arow .sub{display:block;font-size:12px;color:var(--mut);font-weight:400;margin-top:1px}
.acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.acts form{margin:0}.acts button,.arow button.ghost{padding:5px 11px;font-size:12px;border-radius:6px}
.acts details{position:relative}.acts details>summary{list-style:none;cursor:pointer;padding:5px 11px;border:1px solid var(--line);border-radius:6px;font-size:12px;font-weight:600;background:var(--card)}
.acts details>summary::-webkit-details-marker{display:none}
.acts details .rn{position:absolute;right:0;top:34px;z-index:5;display:flex;gap:6px;padding:8px;background:var(--card);border:1px solid var(--line);border-radius:8px;box-shadow:var(--sh);min-width:260px}
.acts details .rn input{padding:6px 8px;font-size:13px}
button.danger{color:var(--con);border-color:color-mix(in srgb,var(--con) 40%,var(--line))}
.empty{padding:34px 16px;text-align:center;color:var(--mut)}
.cmpbar{position:sticky;bottom:12px;display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 14px;margin-top:12px}
.cmpbar form{margin:0}
.chip{display:inline-block;font-size:11px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--soft);color:var(--mut);border:1px solid var(--line)}
@media (max-width:640px){.arow{grid-template-columns:auto 1fr}.arow>.acts,.arow>.when{grid-column:2}.arow>.when{display:none}.acts{justify-content:flex-start}}
/* results */
.gv-card{padding:0}.gv-card>summary{cursor:pointer;padding:12px 16px;display:flex;gap:10px;justify-content:space-between;align-items:center;flex-wrap:wrap;font-weight:600}
.gv-card .gb{padding:0 16px 14px;border-top:1px solid var(--line)}.gv-card .gb>*{margin-top:8px}
.gv-card ul{margin:6px 0 0;padding-left:18px}.gv-card li{margin-bottom:4px;font-size:13px}
.fileline{margin-top:8px}.fileline summary{cursor:pointer;font-size:12px;color:var(--mut);font-weight:600}
.fileline div{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.chg{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}
.chg details{border:1px solid var(--line);border-radius:10px;padding:8px 12px}.chg summary{cursor:pointer;font-weight:600;font-size:14px}
.chg ul{margin:6px 0 0;padding-left:18px;font-size:12px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}html{scroll-behavior:auto}}
@media print{
table.gaps{font-size:11px}table.gaps tr{break-inside:avoid}table.gaps thead{display:table-header-group}
body{background:#fff;color:#000}header{position:static;border:0}.strip button,.drop,button{box-shadow:none}
.card,details.qrow,details.fold{box-shadow:none;break-inside:avoid}
details>*{display:block!important}details>summary{list-style:none}
html.js .tabpanel{display:block!important}.tabs{display:none}
form,.nop{display:none!important}}
.busy{position:fixed;inset:0;z-index:100;display:none;place-items:center;padding:16px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
.busy.on{display:grid}
.busy-card{width:min(440px,100%);background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--sh);padding:28px 26px}
.busy-card h3{margin:14px 0 2px;font-size:18px}
.busy-card p{margin:0 0 16px;color:var(--mut);font-size:13px}
.busy-spin{width:34px;height:34px;border-radius:50%;border:3px solid var(--line);border-top-color:var(--acc);animation:busyspin .9s linear infinite}
@keyframes busyspin{to{transform:rotate(360deg)}}
.busy-steps{list-style:none;margin:0;padding:0;display:grid;gap:10px;font-size:14px}
.busy-steps li{display:flex;align-items:center;gap:10px;color:var(--mut)}
.busy-steps li::before{content:"";width:14px;height:14px;border-radius:50%;border:2px solid var(--line);flex:none}
.busy-steps li.act{color:var(--ink);font-weight:600}
.busy-steps li.act::before{border-color:var(--acc);border-top-color:transparent;animation:busyspin .9s linear infinite}
.busy-steps li.done{color:var(--ink)}
.busy-steps li.done::before{background:var(--ok);border-color:var(--ok)}
.busy-bar{height:4px;border-radius:4px;background:var(--soft);overflow:hidden;margin-top:18px}
.busy-bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .6s ease}
"""

JS = """
(function(){
var $=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
window.addEventListener('pageshow',function(e){if(e.persisted){var o=document.getElementById('busy-overlay');if(o)o.classList.remove('on');$('button').forEach(function(b){b.disabled=false})}});
$('form[data-busy]').forEach(function(f){
  f.addEventListener('submit',function(){
    var ov=document.getElementById('busy-overlay');if(!ov)return;
    var inp=f.querySelector('input[type=file]'),n=inp&&inp.files?inp.files.length:0;
    var sub=document.getElementById('busy-sub');
    if(sub)sub.textContent=n?(n+(n===1?' file':' files')+' received. This usually takes a few seconds.'):'This usually takes a few seconds.';
    ov.classList.add('on');
    $('button',document).forEach(function(b){b.disabled=true});
    var st=$('.busy-steps li',ov),bar=$('.busy-bar i',ov)[0],i=0;
    function paint(){st.forEach(function(li,k){li.className=k<i?'done':(k===i?'act':'')});
      if(bar)bar.style.width=Math.round((i+1)/st.length*90)+'%'}
    paint();
    setInterval(function(){if(i<st.length-1){i++;paint()}},2200);
  });
});
var tabBtns=$('.tabs button[data-tab]');
function showTab(id){
  tabBtns.forEach(function(b){var on=b.dataset.tab===id;b.classList.toggle('on',on);b.setAttribute('aria-selected',on)});
  $('.tabpanel').forEach(function(p){p.classList.toggle('on',p.id===id)});
}
function jump(id){showTab(id);history.replaceState(null,'','#'+id);var t=$('.tabs')[0];if(t&&t.getBoundingClientRect().top<0)t.scrollIntoView()}
if(tabBtns.length){
  tabBtns.forEach(function(b){b.addEventListener('click',function(){jump(b.dataset.tab)})});
  var h=location.hash.slice(1);
  showTab(tabBtns.some(function(b){return b.dataset.tab===h})?h:tabBtns[0].dataset.tab);
}
var on=null,strip=$('.strip button');
function applyFilter(code){
  on=on===code?null:code;
  strip.forEach(function(x){x.classList.toggle('on',x.dataset.f===on)});
  $('details.qrow').forEach(function(r){r.style.display=(!on||r.dataset.status===on)?'':'none'});
  $('h2.sec').forEach(function(h){var n=h.nextElementSibling,v=false;
    while(n&&n.classList.contains('qrow')){if(n.style.display!=='none')v=true;n=n.nextElementSibling}
    h.style.display=v?'':'none'});
}
strip.forEach(function(b){b.addEventListener('click',function(){applyFilter(b.dataset.f)})});
$('[data-goto]').forEach(function(b){b.addEventListener('click',function(){
  jump(b.dataset.goto);if(b.dataset.f){on=null;applyFilter(b.dataset.f)}})});
$('form[data-wizard]').forEach(function(f){
  var steps=$('.step',f),i=0,bar=$('.wz-bar i',f)[0],cnt=$('.wz-count',f)[0],grp=$('.wz-group',f)[0],
      prev=$('.wz-prev',f)[0],next=$('.wz-next',f)[0],sub=$('.wz-submit',f)[0],ans=$('.wz-answered',f)[0];
  function answered(s){return $('input,select,textarea',s).some(function(e){
    return (e.type==='radio'||e.type==='checkbox')?e.checked:(e.value||'').trim()!==''})}
  function render(){
    steps.forEach(function(s,k){s.classList.toggle('on',k===i)});
    cnt.textContent='Question '+(i+1)+' of '+steps.length;
    grp.textContent=steps[i].dataset.group||'';
    bar.style.width=((i+1)/steps.length*100)+'%';
    prev.disabled=i===0;next.hidden=i===steps.length-1;
    sub.classList.toggle('ghost',i!==steps.length-1);
    ans.textContent=steps.filter(answered).length+' answered \\u00b7 skip any you like';
  }
  function go(k){i=Math.max(0,Math.min(steps.length-1,k));render();
    if(f.getBoundingClientRect().top<70)f.scrollIntoView({block:'start'})}
  prev.addEventListener('click',function(){go(i-1)});
  next.addEventListener('click',function(){go(i+1)});
  f.addEventListener('click',function(e){
    var t=e.target;if(t.type!=='radio')return;
    if(t.dataset.was==='1'){t.checked=false;t.dataset.was='0';render();return}
    $('input[type=radio]',t.closest('.step')).forEach(function(r){r.dataset.was='0'});
    t.dataset.was='1';render();
    if(i<steps.length-1)setTimeout(function(){go(i+1)},260);
  });
  f.addEventListener('change',render);
  f.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();if(i<steps.length-1)go(i+1)}});
  render();
});
$('.drop input[type=file]').forEach(function(inp){
  var LIM=5*1024*1024,MAXF=25,SHOW=5,open=false;
  var m=document.getElementById('dropmsg'),box=document.getElementById('filelist');
  function size(n){return n>=1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.round(n/1024))+' KB'}
  function ext(f){var i=f.name.lastIndexOf('.');return i<0?'FILE':f.name.slice(i+1).toUpperCase()}
  function render(){
    var fs=Array.prototype.slice.call(inp.files);
    if(!fs.length){if(m)m.textContent='Drag & drop files here, or click to browse';if(box)box.innerHTML='';return}
    var tot=0,kinds={};fs.forEach(function(f){tot+=f.size;var k=ext(f);kinds[k]=(kinds[k]||0)+1});
    var bad=fs.filter(function(f){return f.size>LIM}).length+(fs.length>MAXF?fs.length-MAXF:0);
    if(m)m.textContent=fs.length+(fs.length===1?' file':' files')+' · '+size(tot)+' · '+Object.keys(kinds).map(function(k){return k+' '+kinds[k]}).join(', ');
    if(!box)return;
    box.innerHTML='';
    (open?fs:fs.slice(0,SHOW)).forEach(function(f,i){
      var r=document.createElement('div');r.className='frow'+(f.size>LIM||i>=MAXF?' bad':'');
      var n=document.createElement('span');n.className='fname';n.textContent=f.name;n.title=f.name;
      var s=document.createElement('span');s.className='fsize';s.textContent=f.size>LIM?size(f.size)+' · over 5 MB':(i>=MAXF?'over 25-file limit':size(f.size));
      var x=document.createElement('button');x.type='button';x.className='fx';x.textContent='✕';x.setAttribute('aria-label','Remove '+f.name);
      x.addEventListener('click',function(){var dt=new DataTransfer();fs.forEach(function(g){if(g!==f)dt.items.add(g)});inp.files=dt.files;render()});
      r.appendChild(n);r.appendChild(s);r.appendChild(x);box.appendChild(r)});
    if(fs.length>SHOW){var t=document.createElement('button');t.type='button';t.className='fmore';
      t.textContent=open?'Show less':'+'+(fs.length-SHOW)+' more';
      t.addEventListener('click',function(){open=!open;render()});box.appendChild(t)}
    if(bad){var w=document.createElement('div');w.className='fwarn';w.textContent=bad+' file(s) exceed the limits and will be rejected — remove them to continue.';box.appendChild(w)}}
  inp.addEventListener('change',function(){open=false;render()})});
})();
"""


LOGO = ("<svg viewBox='0 0 24 24' fill='none' stroke='#fff' stroke-width='2.2' stroke-linecap='round' "
        "stroke-linejoin='round'><path d='M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z'/><path d='M9 12l2 2 4-4'/></svg>")


import contextvars  # noqa: E402
_NAV = contextvars.ContextVar('dg_nav', default="<a href='/login'>Sign in</a><a class='cta' href='/register'>Create account</a>")
_NAV_USER = ("<a href='/'>Workspace</a><a href='/my-assessments'>My assessments</a><span class='vr'></span>"
             "<form method='post' action='/logout'><button type='submit' class='ghost'>Log out</button></form>")
_NAV_GUEST = ("<span class='gchip' title='Temporary guest session'>Guest demo &middot; ~30 min</span><span class='vr'></span>"
              "<a href='/login'>Sign in</a><a class='cta' href='/register'>Create account</a>")


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    mode = _mode_label()
    return HTMLResponse(status_code=status_code, content=(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<script>document.documentElement.classList.add('js')</script>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        f"<header><a class='brand' href='/'><span class='logo'>{LOGO}</span><span><h1>DriftGuard</h1>"
        f"<p>SOC 2 CC6/CC7 readiness signals from a "
        f"grounded knowledge base. Not an audit opinion.</p></span></a><span class='sp'></span>"
        f"<nav class='nop hnav'>{_NAV.get()}</nav>"
        f"<span class='tag t-mode nop'>{mode}</span></header>"
        f"<main>{body}</main><script>{JS}</script></body></html>"
    ))


def _control(name: str, q: dict, placeholder: str = "Type your answer…") -> str:
    """Render an answer control as tap-friendly option cards."""
    kind = q["answer_type"]
    if kind == "single_select":
        return "<div class='opts'>" + "".join(
            f"<label class='opt'><input type='radio' name='{name}' value='{_esc(o)}'>"
            f"<span class='mk'></span><span>{_esc(o)}</span></label>" for o in q["options"]) + "</div>"
    if kind == "multi_select":
        return "<div class='hint'>Select all that apply</div><div class='opts'>" + "".join(
            f"<label class='opt'><input type='checkbox' name='{name}' value='{_esc(o)}'>"
            f"<span class='mk sq'></span><span>{_esc(o)}</span></label>" for o in q["options"]) + "</div>"
    return f"<textarea name='{name}' placeholder='{_esc(placeholder)}'></textarea>"


def _wizard(action: str, steps: list[str], submit: str, hidden: str = "") -> str:
    """One question per screen with progress; every step stays in the DOM and the
    form posts exactly the same field names as before (no-JS shows all steps)."""
    return (
        f"<form method='post' action='{action}' class='wizard' data-wizard>{hidden}"
        "<div class='wz-top'><div class='wz-bar'><i></i></div><div class='wz-meta'>"
        "<span class='wz-count'></span><span class='wz-group'></span></div></div>"
        f"{''.join(steps)}"
        "<div class='wz-nav'><button type='button' class='ghost wz-prev'>&larr; Back</button>"
        "<span class='mid wz-answered'></span>"
        "<button type='button' class='wz-next'>Next &rarr;</button>"
        f"<button type='submit' class='wz-submit ghost'>{submit}</button></div></form>"
    )


def _tabs(items: list[tuple[str, str, object, str]]) -> str:
    """items: (id, label, badge-or-None, html). Panels are all server-rendered."""
    bar = "".join(
        f"<button type='button' role='tab' data-tab='{i}'>{l}"
        + (f"<span class='bd'>{b}</span>" if b not in (None, "") else "") + "</button>"
        for i, l, b, _ in items)
    panels = "".join(f"<section class='tabpanel' id='{i}'>{h}</section>" for i, _, _, h in items)
    return f"<nav class='tabs nop' role='tablist' aria-label='Result sections'>{bar}</nav>{panels}"


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


async def _form(request: Request) -> dict[str, list[str]]:
    """Parse a urlencoded form body without pulling in python-multipart."""
    return parse_qs((await request.body()).decode("utf-8"))


def _public_landing() -> HTMLResponse:
    return _page("DriftGuard", """
<div class='hero'>
  <span class='tag t-mode'>EVIDENCE-FIRST COMPLIANCE</span>
  <h2>See what your evidence actually proves.</h2>
  <p>Try a bounded, temporary assessment without creating an account, or sign in for saved assessments, exports and history.</p>
</div>
<div class='choices'>
  <div class='card choice main'><h3>Try DriftGuard</h3>
    <p>Temporary guest workspace. Up to 3 files, 5 MB each and 10 MB total. Results are not saved to an account.</p>
    <form method='post' action='/guest/start'><button class='btn-main' type='submit'>Try without signing in</button></form>
  </div>
  <div class='card choice'><h3>Full workspace</h3>
    <p>Save assessments, compare runs, export reports and keep an assessment history.</p>
    <div class='actions'><a class='pill' href='/login'>Sign in</a><a class='pill' href='/register'>Create account</a></div>
  </div>
</div>
<p class='disclaimer'>Guest mode is for evaluation. Do not upload highly sensitive or regulated information to a demo environment.</p>
""")


@app.post("/guest/start")
def guest_start():
    token = secrets.token_urlsafe(32)
    r = RedirectResponse('/guest', status_code=303)
    r.set_cookie(_GUEST_COOKIE, token, httponly=True, samesite='strict',
                 secure=os.getenv('DRIFTGUARD_SECURE_COOKIES', '1' if os.getenv('DRIFTGUARD_ENV') == 'production' else '0') == '1',
                 max_age=30*60)
    return r


@app.get('/guest', response_class=HTMLResponse)
def guest_workspace(request: Request):
    if not request.cookies.get(_GUEST_COOKIE):
        return RedirectResponse('/', status_code=303)
    types = ' '.join(e.lstrip('.').upper() for e in SUPPORTED)
    return _page('Guest Demo', f"""
<div class='hero'><span class='tag t-mode'>GUEST DEMO</span><h2>Try a temporary evidence assessment</h2>
<p>Your guest assessment is isolated from registered users and is not written to account history.</p></div>
<div class='card'><form method='post' action='/guest/analyze' enctype='multipart/form-data'>
<label for='vendor'>Company / test name</label><input type='text' id='vendor' name='vendor' required maxlength='200' placeholder='Demo Company'>
<label for='files' style='margin-top:14px'>Evidence files</label><input type='file' id='files' name='files' multiple required accept='{','.join(SUPPORTED)}'>
<p class='small'>{types} · maximum 3 files · 5 MB each · 10 MB total</p>
<button type='submit'>Analyze guest evidence</button></form>
<form method='post' action='/guest/sample' style='margin-top:12px'><button type='submit' class='ghost'>Use sample evidence instead</button></form></div>
<div class='card small'><strong>Guest limits:</strong> no saved history, exports, integrations or API access. Create an account when you want a persistent workspace.</div>
""")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if _auth_required() and _user_id(request) is None:
        return _public_landing()
    mode = _mode_label()
    types =" ".join(e.lstrip(".").upper() for e in SUPPORTED)
    return _page("DriftGuard", f"""
<div class="hero">
  <span class="tag t-mode">MODE: {mode}</span>
  <h2>Know where you stand on <em>SOC&nbsp;2</em> before the auditor does</h2>
  <p>Readiness review of CC6/CC7 from your existing security documentation. Material is
  analysed only against DriftGuard's knowledge base; nothing here is a compliance conclusion.</p>
  <div class="steps3"><span><b>1</b>Upload evidence</span><span><b>2</b>See what is established</span><span><b>3</b>Answer only what is unclear</span></div>
</div>
<div class="choices">
<div class="card choice main">
  <h3><i>&#128196;</i>SOC 2 Readiness Assessment</h3>
  <p class="small">Recommended. Drop in policies, access reviews or registers and get a result in one pass.</p>
  <form id="analyze-form" method="post" action="/analyze" enctype="multipart/form-data" data-busy>
    <div><label for="vendor">Company</label>
    <input type="text" id="vendor" name="vendor" required placeholder="Acme Cloud Inc."></div>
    <div class="grow"><label for="files">Upload security material</label>
    <span class="drop" id="drop"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"/></svg>
    <b id="dropmsg">Drag &amp; drop files here, or click to browse</b>
    <input type="file" id="files" name="files" multiple
           accept="{','.join(SUPPORTED)}"
           ondragenter="this.parentNode.classList.add('over')" ondragleave="this.parentNode.classList.remove('over')" ondrop="this.parentNode.classList.remove('over')"></span>
    <div id="filelist" aria-live="polite"></div>
    <div class="small" style="margin-top:6px">{types} &middot; max 25 files per browser/API request, 5 MB each</div></div>
    <button type="submit" class="btn-main">Analyze Documents</button>
  </form>
  <form method="post" action="/analyze-sample" data-busy>
    <button type="submit" class="btn-main">Try with sample evidence pack</button>
  </form>
  <div id="busy-overlay" class="busy" role="status" aria-live="polite">
    <div class="busy-card">
      <div class="busy-spin"></div>
      <h3>Analysing your evidence</h3>
      <p id="busy-sub">This usually takes a few seconds.</p>
      <ul class="busy-steps">
        <li>Reading files</li><li>Classifying documents</li><li>Extracting facts</li>
        <li>Validating provenance</li><li>Mapping to questions</li>
      </ul>
      <div class="busy-bar"><i></i></div>
    </div>
  </div>
</div>
<div class="card choice">
  <h3><i>&#9998;</i>Prefer to answer questions?</h3>
  <p class="small">Walk through the full questionnaire one question at a time. Skip anything you like.</p>
  <form method="post" action="/assessment">
    <div class="grow"><label for="mvendor">Answer the full questionnaire instead</label>
    <input type="text" id="mvendor" name="vendor" required placeholder="Acme Cloud Inc."></div>
    <button type="submit" class="btn-main ghost">Start Manual Assessment</button>
  </form>
</div>
</div>""")


@app.post("/api/evidence-map")
async def evidence_map(request: Request):
    """CP009 deterministic evidence-to-question mapping for uploaded files."""
    authorize_api(request)
    async with request.form() as form:
        payloads = await read_uploads(form)
    if not payloads:
        return JSONResponse({"error": "No files supplied"}, status_code=400)
    analysis = analyze_artifacts(payloads)
    mapping = map_questionnaire(analysis)
    return JSONResponse({
        "analysis_errors": list(analysis.errors),
        "mapping": mapping.to_dict(),
        "intelligence": build_intelligence(analysis, mapping),
        "disclaimer": "Evidence mapping is not a question answer or compliance conclusion.",
    })


_STRUCTURED_TARGETS = {
    "USER_ACCESS_REVIEW": (("QN-ACCESS-001-Q03", "the most recent completed review"),
                           ("QN-ACCESS-001-Q04", "the population covered by the most recent review")),
    "PRIVILEGED_ACCOUNT_INVENTORY": (("QN-ACCESS-001-Q08", "a privileged access review or inventory"),),
    "ENDPOINT_PROTECTION_COVERAGE": (("QN-NETSEC-001-Q06", "measured protective-software coverage against an inventory"),),
    "SECURITY_LOG_COVERAGE": (("QN-OPS-001-Q02", "measured security-log source coverage"),),
    "ACCESS_REVIEW_LOG": (("QN-ACCESS-001-Q03", "the most recent completed review"),
                          ("QN-ACCESS-001-Q04", "the population covered by the most recent review")),
    "PRIVILEGED_APPROVAL_LIST": (("QN-ACCESS-001-Q08", "a privileged access review or inventory"),),
    "VULNERABILITY_REMEDIATION": (("QN-OPS-001-Q07", "operating evidence of scan coverage"),),
    "INCIDENT_REGISTER": (("QN-OPS-001-Q06", "completed root-cause/postmortem record"),),
}


def _apply_structured_evidence_results(result, blocked=frozenset()):
    """Operating evidence from validated tabular files moves its question forward.

    Clean (SUPPORTED) evidence completes a question whose design side is already
    established (ESTABLISHED) and otherwise supports it as PARTIAL; evidence with
    rule deviations (NEEDS_REVIEW) asks for clarification. `blocked` holds questions
    with cross-file deviations, which never reach ESTABLISHED. Conflicts are never
    downgraded, and an unrecognized file never appears here at all."""
    from documents import Fact, ESTABLISHED, PARTIAL, CLARIFICATION, NOT_ESTABLISHED
    byid = {a.question_id: a for a in result.areas}
    for e in result.evidence:
        if e.state not in {"SUPPORTED", "NEEDS_REVIEW"}: continue
        if not e.facts: continue
        p = next((pp for f in e.facts for pp in f.provenance), None)
        for qid, label in _STRUCTURED_TARGETS.get(e.evidence_type, ()):
            a = byid.get(qid)
            if a is None: continue
            fact = Fact(label, f"{label}: {e.evidence_type} validated as {e.state}",
                        e.filename, (f"{p.sheet} {p.locator}".strip() if p else ""),
                        (getattr(p, "excerpt", "") if p else ""), "OPERATING_EVIDENCE",
                        "deterministic-structured", "TABULAR", "OPERATING_EVIDENCE")
            if (e.state == "SUPPORTED" and a.status == PARTIAL and qid not in blocked
                    and a.missing_facts and set(a.missing_facts) <= {label}):
                a.status = ESTABLISHED
                a.reason = (f"Design evidence is established and operating evidence ({e.evidence_type}, "
                            f"{e.filename}) shows no deviation from the stated rule.")
                a.known_facts.append(fact)
                a.missing_facts = []
                continue
            if e.state == "NEEDS_REVIEW" and a.status in {PARTIAL, NOT_ESTABLISHED}:
                bad = "; ".join(c.detail for c in e.checks if c.state == "NEEDS_REVIEW")[:300]
                a.status = CLARIFICATION
                a.reason = f"Operating evidence ({e.evidence_type}, {e.filename}) needs review: {bad}"
                a.known_facts.append(fact)
                continue
            if a.status != NOT_ESTABLISHED: continue
            a.status = PARTIAL if e.state == "SUPPORTED" else CLARIFICATION
            a.reason = (f"Operating evidence supplied ({e.evidence_type}, {e.filename}); "
                        "the documented requirement (design evidence) is still needed.")
            a.known_facts.append(fact)
            a.missing_facts = [m for m in a.missing_facts if m != label]


def _apply_cross_file_findings(result, findings):
    """Deviations found by comparing files (e.g. IdP vs approved list) ask for review.

    CONFLICT is left untouched; no deviation is ever reported as a control failure."""
    from documents import Fact, CONFLICT, CLARIFICATION
    byid = {a.question_id: a for a in result.areas}
    for qid, f in findings:
        a = byid.get(qid)
        if a is None: continue
        ids = ", ".join(i for _, i in f.records[:8]) + (" ..." if len(f.records) > 8 else "")
        if a.status != CONFLICT:
            a.status = CLARIFICATION
            a.reason = f"{f.title} ({len(f.records)}): {ids}. {f.detail} Confirm or provide remediation evidence."
        a.known_facts.append(Fact(f.code, f"{f.title}: {ids}", "cross-file comparison", f"{len(f.records)} records",
                                  ids, "OPERATING_EVIDENCE", "deterministic-structured", "TABULAR", "OPERATING_EVIDENCE"))


def _contradiction_block(a) -> str:
    rows = [c for c in a.semantic_conflicts if c.get("kind") == "RULE_BASED_POLARITY"]
    if not rows:
        return ""
    items = "".join(f"<li><strong>{_esc(c['topic'])}</strong>: {_esc(c['source_file'])} says "
                    f"&ldquo;{_esc(c['deterministic_value'])}&rdquo; but {_esc(c['other_source_file'])} says "
                    f"&ldquo;{_esc(c['semantic_value'])}&rdquo;</li>" for c in rows)
    return f"<div class='card alert' role='alert'><strong>Cross-document contradictions</strong><ul>{items}</ul></div>"


def _apply_graph_question_results(result):
    """Promote provenance-bearing graph observations into relevant question contracts."""
    from documents import Fact, CONFLICT, PARTIAL
    graph=result.evidence_graph
    if graph is None: return
    targets={
      'HR roster ↔ IdP identities':'QN-ACCESS-001-Q06',
      'termination ↔ account disablement':'QN-ACCESS-001-Q06',
      'asset inventory ↔ endpoint protection':'QN-NETSEC-001-Q06',
      'vulnerability ↔ remediation ticket':'QN-OPS-001-Q07',
    }
    byid={a.question_id:a for a in result.areas}
    for o in graph.observations:
        qid=targets.get(o.relationship)
        if not qid or qid not in byid: continue
        a=byid[qid]
        if o.relationship=='asset inventory ↔ endpoint protection' and o.code in {'CROSS-ARTIFACT-CONFLICT','EDR-COVERAGE-GAP','COVERAGE-GAP'}:
            a.status=PARTIAL
        elif o.state=='CONFLICT': a.status=CONFLICT
        elif o.code=='COVERAGE-GAP' and a.status not in {CONFLICT}: a.status=PARTIAL
        else: continue
        a.reason=o.detail
        for p in o.provenance:
            a.known_facts.append(Fact('cross-artifact observation',o.detail,p.filename,p.locator,p.excerpt,'OPERATING_EVIDENCE','deterministic-graph','TABULAR','OPERATING_EVIDENCE'))

class _RunCtx:
    """Mutable state handed from stage to stage; the only thing a stage reads or writes."""

    def __init__(self, vendor, payloads, assessment_date=None, assessment_id=None):
        self.vendor, self.payloads_in, self.date, self.assessment_id = vendor, list(payloads), assessment_date, assessment_id
        self.documents, self.errors, self.extraction, self.payloads = [], [], [], []
        self.workbooks, self.classification, self.evidence = {}, {}, []
        self.result = self.sufficiency = self.report = self.summary = None


def _st_extract(ctx):
    safe_event("assessment_started", file_count=len(ctx.payloads_in))
    ctx.documents, ctx.errors, ctx.extraction, ctx.payloads = extract_many_detailed(ctx.payloads_in)   # duplicates processed once
    if not ctx.payloads_in:
        ctx.errors.append("no files were uploaded")


def _st_classify(ctx):
    """Structural classification of tabular files; parsed workbooks are reused by validate."""
    from evidence.classify import classify
    from evidence.tabular import TabularError, is_tabular, read_tabular
    names = [n for n, _ in ctx.payloads]
    for name, data in ctx.payloads:
        if not is_tabular(name):
            continue
        try:
            wb = read_tabular(name, data)
        except TabularError:
            continue                       # validate reports it as unreadable
        c = classify(wb)
        ctx.classification[name] = dict(evidence_type=c.evidence_type, supported=bool(c.supported), confidence=str(c.confidence))
        if names.count(name) == 1:         # same-named files must not share a parsed workbook
            ctx.workbooks[name] = wb


def _st_validate(ctx):
    ctx.evidence = analyze_evidence(ctx.payloads, as_of=ctx.date, workbooks=ctx.workbooks)


def _st_map(ctx):
    assessment_date = ctx.date
    result = ANALYZER.analyze(ctx.vendor[:200], ctx.documents, ctx.errors, demo_mode_enabled(), ctx.evidence, assessment_date=assessment_date)
    evidence, payloads = ctx.evidence, ctx.payloads
    # Backup execution proves runs, not recoverability. Surface the distinction when no restore test exists.
    if any(e.evidence_type=='BACKUP_JOB_REPORT' for e in evidence) and not any(f.key=='restore_result' for f in result.recovery.facts):
        from bcp_dr import RecoveryAssessment, RecoveryIssue
        from narrative_intelligence import FactProvenance
        be=next(e for e in evidence if e.evidence_type=='BACKUP_JOB_REPORT')
        p=None
        for f in be.facts:
            if f.provenance: p=f.provenance[0]; break
        prov=(FactProvenance(p.filename, f'{p.sheet} {p.locator}', p.excerpt, table=p.sheet),) if p else ()
        issue=RecoveryIssue('BACKUP-RESTORE-NOT-PROVEN','NEEDS_REVIEW','Backup runs are evidenced; recoverability is not proven because no restore-test evidence was supplied.',prov)
        result.recovery=RecoveryAssessment(result.recovery.facts,result.recovery.issues+(issue,))
    from evidence.graph import graph_from_files
    result.evidence_graph = graph_from_files(payloads)
    from evidence.operational_registers import reconcile
    cross = reconcile(payloads, as_of=assessment_date)
    _apply_structured_evidence_results(result, frozenset(q for q, _ in cross))
    _apply_cross_file_findings(result, cross)
    _apply_graph_question_results(result)
    result.files_received = len(ctx.payloads_in)
    result.extraction = [r.to_dict() for r in ctx.extraction]
    from evidence.reproducibility import run_stamp
    result.run_stamp = run_stamp(ctx.payloads_in, assessment_date, result.semantic_status)
    if ctx.assessment_id:
        result.assessment_id = ctx.assessment_id
    ctx.result = result
    safe_event("assessment_completed", assessment_id=result.assessment_id, files_received=len(payloads), files_parsed=len(ctx.documents), parse_errors=len(ctx.errors))


def _st_sufficiency(ctx):
    """Per-question sufficiency dimensions over the same files (not stored on the assessment)."""
    from evidence.sufficiency import evaluate_sufficiency
    analysis = analyze_artifacts(ctx.payloads)
    suff = evaluate_sufficiency(analysis, map_questionnaire(analysis)).to_dict()
    tally: dict[str, int] = {}
    for r in suff["requirements"]:
        for d in r["dimensions"]:
            tally[d["state"]] = tally.get(d["state"], 0) + 1
    ctx.sufficiency = dict(requirements=len(suff["requirements"]), dimension_states=tally)


def _st_report(ctx):
    from evidence.report import build_question_reports
    rep = build_question_reports(ctx.result.areas, ctx.result.extraction)
    ctx.report = dict(questions=len(rep["questions"]), evidence_missing_groups=len(rep["evidence_missing"]),
                      unread_files=len(rep["unread_material"]), duplicate_files=len(rep["duplicates"]))
    ctx.summary = dict(sufficiency=ctx.sufficiency, report=ctx.report)


def _stages_core():
    return [_st_extract, _st_classify, _st_validate, _st_map]


def analyze_payloads(vendor: str, payloads, *, assessment_date=None, assessment_id=None):
    """Shared CP016 orchestration used by web and offline pack runner (same stages as the background job)."""
    ctx = _RunCtx(vendor, payloads, assessment_date, assessment_id)
    for stage in _stages_core():
        stage(ctx)
    return ctx.result

@app.post('/guest/analyze')
async def guest_analyze(request: Request):
    guest = request.cookies.get(_GUEST_COOKIE)
    if not guest:
        return RedirectResponse('/', status_code=303)
    if not _rate_ok(f'guest:{guest}', 5, 3600):
        return _guest_error('Guest assessment limit reached. Please try again later or create an account.', 429)
    async with request.form() as form:
        vendor = str(form.get('vendor') or 'Guest Demo')[:200]
        payloads = await read_uploads(form)
    if not payloads:
        return _guest_error('No files were uploaded.', 400)
    if (len(payloads) > _GUEST_MAX_FILES or sum(len(d) for _, d in payloads) > _GUEST_MAX_TOTAL_BYTES
            or any(len(d) > _GUEST_MAX_FILE_BYTES for _, d in payloads)):
        return _guest_error('Guest limits: 3 files, 5 MB per file, 10 MB total.', 413)
    result = analyze_payloads(vendor, payloads)
    DOC_ASSESSMENTS[result.assessment_id] = result
    _ASSESSMENT_OWNERS[('doc-results', result.assessment_id)] = f'guest:{guest}'
    return RedirectResponse(f'/doc-results/{result.assessment_id}', status_code=303)


@app.post('/guest/sample')
def guest_sample(request: Request):
    guest = request.cookies.get(_GUEST_COOKIE)
    if not guest:
        return RedirectResponse('/', status_code=303)
    if not _rate_ok(f'guest:{guest}', 5, 3600):
        return _guest_error('Guest assessment limit reached. Please try again later or create an account.', 429)
    payloads = [(p.name, p.read_bytes()) for p in sorted(SAMPLE_PACK_DIR.glob('*')) if p.is_file() and p.suffix.lower() in SUPPORTED][:_GUEST_MAX_FILES]
    if not payloads:
        return _guest_error('Sample evidence pack not found.', 404)
    result = analyze_payloads('Guest Sample Company', payloads)
    DOC_ASSESSMENTS[result.assessment_id] = result
    _ASSESSMENT_OWNERS[('doc-results', result.assessment_id)] = f'guest:{guest}'
    return RedirectResponse(f'/doc-results/{result.assessment_id}', status_code=303)


@app.post("/analyze")
async def analyze(request: Request):
    async with request.form() as form:
        vendor = str(form.get("vendor") or "Unnamed vendor")[:200]
        payloads = await read_uploads(form)
    if not payloads:
        return JSONResponse({"error": "no files were uploaded"}, status_code=400)
    result = analyze_payloads(vendor, payloads)
    DOC_ASSESSMENTS[result.assessment_id] = result
    _bind_owner("doc-results", result.assessment_id, request)
    assessment_id_var.set(result.assessment_id)
    uid = _user_id(request)
    if uid is not None:
        try:
            UPLOADS.save(uid, result.assessment_id, payloads)
        except (OSError, ValueError) as exc:   # analysis still succeeds; the raw files just are not retained
            log_event("upload_store_failed", code=ErrorCode.STORAGE_FAILED, level=logging.ERROR, error_type=type(exc).__name__)
    return RedirectResponse(f"/doc-results/{result.assessment_id}", status_code=303)


SAMPLE_PACK_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "files"


@app.post("/analyze-sample")
def analyze_sample(request: Request):
    payloads = [(p.name, p.read_bytes()) for p in sorted(SAMPLE_PACK_DIR.glob("*"))
                if p.is_file() and p.suffix.lower() in SUPPORTED]
    if not payloads:
        return JSONResponse({"error": "sample evidence pack not found"}, status_code=404)
    result = analyze_payloads("Sample Company", payloads)
    DOC_ASSESSMENTS[result.assessment_id] = result
    _bind_owner("doc-results", result.assessment_id, request)
    return RedirectResponse(f"/doc-results/{result.assessment_id}", status_code=303)


@app.get("/doc-results/{assessment_id}", response_class=HTMLResponse)
def doc_results(assessment_id: str, request: Request = None) -> HTMLResponse:
    a = _owned_get(DOC_ASSESSMENTS, "doc-results", assessment_id, request)
    if a is None:
        return _page("Not found", "<div class='card'>Unknown assessment. "
                                  "<a href='/'>Start again</a>.</div>", 404)
    from documents import QUESTION_SPECS
    implemented = [x for x in a.areas if x.question_id in QUESTION_SPECS]
    unimplemented = [x for x in a.areas if x.question_id not in QUESTION_SPECS]
    structured_validated = sum(e.evidence_type != "UNCLASSIFIED" for e in a.evidence)
    narrative_analyzed = sum(1 for name in a.documents if Path(name).suffix.lower() not in (".csv", ".xlsx"))
    summary = [
        ("Files received", a.files_received or len(a.documents)),
        ("Files parsed", len(a.documents)),
        ("Structured artifacts validated", structured_validated),
        ("Narrative documents analyzed", narrative_analyzed),
        ("Requirements with evaluation rules", len(implemented)),
        ("Questions evaluated", len(implemented) - sum(x.status == NOT_EVALUATED for x in implemented)),
        ("Questions not evaluated", sum(x.status == NOT_EVALUATED for x in a.areas) + len(unimplemented)),
        ("Not evaluated at runtime", sum(x.status == NOT_EVALUATED for x in a.areas)),
        ("Established", sum(x.status == ESTABLISHED for x in implemented)),
        ("Partial", sum(x.status == PARTIAL for x in implemented)),
        ("Not established", sum(x.status == NOT_ESTABLISHED for x in implemented)),
        ("Clarification", sum(x.status == CLARIFICATION for x in implemented)),
        ("Conflict", sum(x.status == CONFLICT for x in implemented)),
    ]
    cards = "".join(
        f"<div class='card'><div class='n'>{v}</div><div class='l'>{_esc(k)}</div></div>"
        for k, v in summary
    )
    cnt = {k: v for k, v in summary}
    ev_n = cnt["Established"] + cnt["Partial"] + cnt["Not established"] + cnt["Clarification"] + cnt["Conflict"]
    pct = round(100 * (cnt["Established"] + cnt["Partial"]) / ev_n) if ev_n else 0
    # Presentation-only evidence-health signal. It summarizes ingestion/QA quality and
    # never participates in deterministic compliance evaluation.
    received = max(1, a.files_received or len(a.documents))
    parsed_ratio = len(a.documents) / received
    unclassified = sum(e.evidence_type == "UNCLASSIFIED" for e in a.evidence)
    health = max(0, min(100, round(100 * parsed_ratio) - min(30, len(a.errors) * 10)
                              - min(25, unclassified * 5) - min(25, cnt["Conflict"] * 10)))
    health_label = "Strong" if health >= 85 else "Needs attention" if health >= 60 else "Weak"
    gauge = (f"<svg class='gauge' viewBox='0 0 36 36' role='img' aria-label='Readiness {pct}%'>"
             f"<circle cx='18' cy='18' r='15.9' fill='none' stroke='var(--line)' stroke-width='3.5'/>"
             f"<circle cx='18' cy='18' r='15.9' fill='none' stroke='var(--ok)' stroke-width='3.5' stroke-linecap='round' "
             f"stroke-dasharray='{pct} 100' transform='rotate(-90 18 18)' pathLength='100'/>"
             f"<text x='18' y='20.5' text-anchor='middle' font-size='8'>{pct}%</text></svg>")
    strip = "".join(
        f"<button type='button' class='s-{code}' data-f='{code}'><span class='n'>{cnt[lbl]}</span><span class='l'>{lbl}</span></button>"
        for code, lbl in [(ESTABLISHED, "Established"), (PARTIAL, "Partial"), (CLARIFICATION, "Clarification"),
                          (CONFLICT, "Conflict"), (NOT_ESTABLISHED, "Not established")]
    )
    order = [(ESTABLISHED, "Established"), (PARTIAL, "Partial"), (CLARIFICATION, "Clarification"),
             (CONFLICT, "Conflict"), (NOT_ESTABLISHED, "Not established")]
    dist = ("<div class='dist' role='img' aria-label='Status distribution'>"
            + "".join(f"<i class='s-{c}' style='flex:{cnt[l]}' title='{l}: {cnt[l]}'></i>" for c, l in order if cnt[l])
            + "</div>")
    legend = "<div class='legend'>" + "".join(
        f"<button type='button' class='s-{c}' data-goto='t-questions' data-f='{c}'><span class='dot'></span>"
        f"<span><span class='n'>{cnt[l]}</span><div class='l'>{l}</div></span></button>" for c, l in order) + "</div>"
    tags = {ESTABLISHED: "t-ok", PARTIAL: "t-rev", NOT_ESTABLISHED: "t-skip",
            CLARIFICATION: "t-gap", CONFLICT: "t-gap", NOT_EVALUATED: "t-skip"}

    def section(status: str, title: str) -> str:
        rows = [x for x in implemented if x.status == status]
        if not rows:
            return ""
        body = "".join(
            f"<details class='qrow s-{x.status}' data-status='{x.status}'><summary>"
            f"<span><strong>{_esc(x.area)}</strong><div class='small'>{_esc(x.question)}</div></span>"
            f"<span class='tag {tags[x.status]}'>{_esc(x.status.replace('_',' '))}</span></summary><div class='qb'>"
            f"<div><strong>Why:</strong> {_esc(x.reason)}</div><div class='small'>Explanation / known facts</div>"
            + ("".join(
                f"<details class='fnd'><summary>Evidence used: {_esc(f.statement)}</summary>"
                f"<div class='small'><strong>Source provenance:</strong> {_esc(f.source_file)} &middot; "
                f"{_esc(f.source_locator)} &middot; {_esc(f.artifact_type)} &middot; {_esc(f.source_role)} &middot; {_esc(f.extraction_method)}</div>"
                f"<div class='small'><strong>Supporting excerpt:</strong> &ldquo;{_esc(f.snippet[:400])}&rdquo;</div></details>"
                for f in x.known_facts) or "<div class='small'>Evidence used: none.</div>")
            + ("<div class='small'><strong>Contradictions:</strong> eligible evidence disagrees; inspect provenance above.</div>" if x.status == CONFLICT else "<div class='small'><strong>Contradictions:</strong> none surfaced for this question.</div>")
            + "<div class='small'><strong>Evidence rejected:</strong> ineligible source roles, future/invalid dates and ungrounded semantic candidates cannot satisfy the contract; aggregate semantic rejections are shown in Analysis diagnostics.</div>"
            f"<div class='small'><strong>Still unknown:</strong> {_esc('; '.join(m for m in x.missing_facts if m.strip() not in ('', '—')) or 'Nothing further requested')}</div>"
            f"<div class='small'><strong>Evidence still needed:</strong> {_esc('; '.join(x.evidence_needed) or 'Nothing further requested')}</div>"
            f"<details><summary class='small'>details</summary>"
            f"<span class='small'>{_esc(', '.join(x.detail_ids + [x.question_id]))}</span></details>"
            f"</div></details>"
            for x in rows
        )
        return f"<h2 class='sec'>{title} ({len(rows)})</h2>{body}"

    evidence_block = ""
    if a.evidence:
        unclassified_count = sum(e.evidence_type == "UNCLASSIFIED" for e in a.evidence)
        evidence_block = (
            f"<h2>Evidence QA</h2><div class='card'>"
            f"<strong>{sum(build_report(e).exception_count for e in a.evidence)} "
            f"item(s) to look at</strong> across "
            f"{len(a.evidence)} tabular artifact(s); "
            f"<strong>{unclassified_count} unclassified/unvalidated artifact(s)</strong>. "
            f"Zero QA exceptions does not mean an unclassified file passed validation."
            f"<div class='small'>What an "
            f"auditor would ask about first, reconciled by DriftGuard arithmetic "
            f"against the artifact's own numbers.</div>"
            f"<p><a href='/evidence-report/{_esc(a.assessment_id)}'>"
            f"Open the Evidence QA report</a></p></div>"
        )

    recovery_block = ""
    if a.recovery and (a.recovery.facts or a.recovery.issues):
        issue_rows = "".join(
            f"<tr><td>{_esc(i.code)}</td><td>{_esc(i.state)}</td><td>{_esc(i.detail)}</td>"
            f"<td class='small'>{_esc('; '.join(p.filename + ' / ' + p.locator for p in i.provenance))}</td></tr>"
            for i in a.recovery.issues
        ) or "<tr><td colspan='4'>No BCP/DR reconciliation exceptions identified from supplied material.</td></tr>"
        recovery_block = (
            f"<h2>BCP / DR / Backup intelligence</h2><div class='card'>"
            f"<strong>{len(a.recovery.facts)} grounded recovery fact(s)</strong>; "
            f"<strong>{len(a.recovery.issues)} reconciliation item(s)</strong>. "
            f"These are evidence observations, not compliance conclusions.</div>"
            f"<table><tr><th>Check</th><th>State</th><th>Observation</th><th>Provenance</th></tr>{issue_rows}</table>"
        )

    graph_block = ""
    if a.evidence_graph and (a.evidence_graph.edges or a.evidence_graph.observations or a.evidence_graph.coverage):
        coverage_rows = "".join(
            f"<tr><td>{_esc(rel)}</td><td>{v['source']}</td><td>{v['matched']}</td><td>{v['unmatched']}</td><td>{_esc(v['percent'])}%</td></tr>"
            for rel,v in sorted(a.evidence_graph.coverage.items())
        )
        obs_rows = "".join(
            f"<tr><td>{_esc(o.code)}</td><td>{_esc(o.relationship)}</td><td>{_esc(o.detail)}</td><td class='small'>{_esc('; '.join(p.filename + ' / ' + p.locator for p in o.provenance))}</td></tr>"
            for o in a.evidence_graph.observations
        ) or "<tr><td colspan='4'>No cross-artifact exceptions identified from exact/normalized identifiers.</td></tr>"
        graph_block = (
            f"<h2>Cross-artifact evidence graph</h2><div class='card'><strong>{len(a.evidence_graph.edges)} provenance-bearing relationship(s)</strong>; "
            f"<strong>{len(a.evidence_graph.observations)} review observation(s)</strong>. Coverage gaps are not control failures.</div>"
            f"<table><tr><th>Relationship</th><th>Source</th><th>Matched</th><th>Unmatched</th><th>Coverage</th></tr>{coverage_rows}</table>"
            f"<table><tr><th>Check</th><th>Relationship</th><th>Observation</th><th>Provenance</th></tr>{obs_rows}</table>"
        )

    follow = a.follow_ups()
    follow_form = ""
    if follow:
        requests = "".join(
            f"<div class='card'><div class='qid'>{_esc(x.area)} &middot; evidence request</div>"
            f"<div>{_esc(x.prompt)}</div></div>"
            for x in follow if x.kind == "evidence_request"
        )
        steps = []
        for x in [y for y in follow if y.kind == "question"]:
            question = KNOWLEDGE.question(x.questionnaire_id, x.question_id)
            name = f"{x.questionnaire_id}|{x.question_id}"
            steps.append(
                f"<section class='step' data-group='{_esc(x.area)}'>"
                f"<div class='qid'>{_esc(x.area)} &middot; {_esc(x.status.replace('_',' '))}</div>"
                f"<h3 class='qtext'>{_esc(x.prompt)}</h3>"
                f"<div class='why'>why asked: {_esc(x.reason)}</div>"
                f"{_control(name, question)}</section>"
            )
        form_block = _wizard(f"/clarify/{_esc(a.assessment_id)}", steps, "Submit answers") if steps else ""
        follow_form = f"""
<h2>DriftGuard needs clarification</h2><div class="small"><strong>Smart evidence requests:</strong> targeted from the deterministic gaps below.</div>
<div class="card"><p class="small">Only what your material did not settle is shown.</p>
{requests}{form_block}</div>"""
    n_follow = sum(1 for y in follow if y.kind == "question") or len(follow)

    errors = ""
    if a.errors:
        errors = ("<div class='card'><strong>Files not analysed</strong>"
                  + "".join(f"<div class='small'>{_esc(e)}</div>" for e in a.errors)
                  + "</div>")
    mode_note = ""
    if a.mode == "DEMO":
        mode_note = ("<div class='card'><span class='tag t-mode'>DEMO</span> "
                     "Document analysis is running in DEMO mode. <strong>DETERMINISTIC ONLY</strong>. Semantic analysis status: "
                     f"{_esc(a.semantic_status)}. DEMO does not silently simulate model analysis.</div>")

    # Make assessment coverage visible: 29 questions are evaluated, but only a
    # subset has implemented claim contracts. LOCAL does not imply model inference.
    covered = len(implemented)
    uncovered = len(unimplemented)
    no_claim_files = [name for name in a.documents
                      if not any(c.source_filename == name for c in a.claims)]
    diagnostics = (
        "<h2>Why did I get these results?</h2><div class='card'>"
        f"<div><strong>Analysis method (ENGINE-LOCAL-001):</strong> Deterministic grounded extraction is active. Semantic provider: {_esc(a.semantic_status)}; rejected semantic candidates: {a.semantic_rejections}. Only validated semantic facts may enter questionnaire evaluation.</div>"
        f"<div><strong>Supported question coverage (COVERAGE-001):</strong> {covered} of {len(a.areas)} "
        f"question(s) have explicit claim-evaluation contracts; {uncovered} "
        "question(s) lack a contract. NOT_EVALUATED is reserved for genuine runtime inability, not missing implementation.</div>"
        f"<div><strong>Recognized statements (CLAIMS-001):</strong> {len(a.claims)} supported claim(s) "
        "extracted across uploaded files.</div>"
        + ("<div><strong>Files with no recognized statements (CLAIMS-002):</strong> No supported claim recognized in: "
           + _esc(', '.join(no_claim_files))
           + ". This may indicate out-of-scope content OR an unsupported "
           "extractor concept; it is not a control failure.</div>"
           if no_claim_files else "")
        + ("<div><strong>Files without structured validation (EQA-UNSUPPORTED-TYPE):</strong> "
           + _esc(', '.join(e.filename for e in a.evidence
                            if e.evidence_type == 'UNCLASSIFIED'))
           + ": no type-specific structured validation was performed. "
           "Zero QA exceptions is not a pass.</div>"
           if any(e.evidence_type == 'UNCLASSIFIED' for e in a.evidence) else "")
        + "</div>"
    )
    unsupported_section = (
        "<h2>Not yet supported by this evaluation engine "
        f"({len(unimplemented)})</h2>"
        "<div class='card'><p>These questions were included in the questionnaire, "
        "but this local engine has no implemented evidence contract for them. "
        "Do not interpret them as  missing documents, failed controls, or "
        "completed semantic evaluations.</p><details><summary>Show questions "
        "not evaluated</summary><ol>"
        + "".join(f"<li>{_esc(x.question)}</li>" for x in unimplemented)
        + "</ol></details></div>"
    ) if unimplemented else ""
    guide = (
        "<div class='card'><h2 style='margin-top:0'>How to read this assessment</h2>"
        "<p><strong>Established:</strong> the implemented rule found its required "
        "facts in an eligible source. <strong>Partially established:</strong> "
        "some relevant facts were found but additional evidence is needed. "
        "<strong>No supported fact found:</strong> the local extractor did not "
        "find evidence for an implemented rule; this does not prove a control "
        "failed. <strong>Conflict:</strong> eligible evidence sources materially disagree. "
        "<strong>Not evaluated:</strong> the evaluation could not execute at runtime.</p>"
        "<p><strong>Next step:</strong> inspect Analysis "
        "diagnostics below, then open Evidence QA for any tabular files. "
        "Unclassified means no structured validation occurred.</p></div>"
    )
    sev = {CONFLICT: 0, CLARIFICATION: 1, NOT_ESTABLISHED: 2, PARTIAL: 3}
    gaps = sorted((x for x in implemented if x.status in sev), key=lambda x: sev[x.status])
    good_pts, bad_pts = [], []
    if cnt["Established"]:
        names = ", ".join([_esc(x.area) for x in implemented if x.status == ESTABLISHED][:3])
        good_pts.append(f"{cnt['Established']} of {ev_n} evaluated questions are fully established ({names}).")
    if cnt["Partial"]:
        good_pts.append(f"{cnt['Partial']} more are partly supported by your documents.")
    if a.claims:
        good_pts.append(f"{len(a.claims)} supported statement(s) were found in the uploaded files.")
    if cnt["Conflict"]:
        names = ", ".join([_esc(x.area) for x in gaps if x.status == CONFLICT][:2])
        bad_pts.append(f"{cnt['Conflict']} question(s) have sources that disagree ({names}).")
    if cnt["Clarification"]:
        bad_pts.append(f"{cnt['Clarification']} question(s) need clarification from the vendor.")
    if cnt["Not established"]:
        bad_pts.append(f"{cnt['Not established']} question(s) have no supporting evidence yet.")
    top_missing = [m for x in gaps for m in x.missing_facts][:2]
    if top_missing:
        bad_pts.append("Top missing items: " + _esc("; ".join(top_missing)) + ".")
    good_pts, bad_pts = good_pts[:3], bad_pts[:3]
    guest_cta = ("<div class='card'><strong>Guest assessment</strong><p class='small'>This result is temporary. Create an account to save assessments, compare runs and export reports.</p><a class='pill' href='/register'>Create free account</a></div>" if _user_id(request) is None else "")
    key_findings = (
        guest_cta + "<h2>Key findings</h2><div class='card kf'><div class='kf-ok'><strong>What's in place</strong><ul>"
        + ("".join(f"<li>{p}</li>" for p in good_pts) or "<li>Nothing established yet.</li>")
        + "</ul></div><div class='kf-bad'><strong>What's lacking</strong><ul>"
        + ("".join(f"<li>{p}</li>" for p in bad_pts) or "<li>No gaps identified.</li>")
        + "</ul></div></div>"
    )
    from evidence.gap_view import build_gap_view, render_gap_section
    gap_view = build_gap_view(implemented, a.extraction)
    gaps_table = render_gap_section(gap_view, a.assessment_id) if gap_view["groups"] else ""
    docs_chips = "".join(f"<span class='tag t-skip'>{_esc(d)}</span>" for d in a.documents) or "<span class='small'>none</span>"
    semantic_label = ("SEMANTIC ANALYSIS ACTIVE" if a.semantic_status == "SEMANTIC_ACTIVE"
                      else "SEMANTIC ANALYSIS UNAVAILABLE - NEEDS_REVIEW"
                      if a.semantic_status in {"SEMANTIC_UNAVAILABLE", "NEEDS_REVIEW"} else a.semantic_status)
    def _sig(ok, good, bad):
        return f"<li>{'&#10003;' if ok else '&#9888;'} {_esc(good if ok else bad)}</li>"
    health_card = ("<div class='card'><strong>Evidence quality signals</strong><ul class='small'>"
        + _sig(parsed_ratio >= 1, f"All {received} file(s) parsed", f"{len(a.documents)} of {received} file(s) parsed")
        + _sig(not a.errors, "No ingestion errors", f"{len(a.errors)} ingestion error(s)")
        + _sig(not unclassified, "No unclassified artifacts", f"{unclassified} unclassified artifact(s)")
        + _sig(not cnt["Conflict"], "No evidence conflicts", f"{cnt['Conflict']} conflict(s) detected")
        + "</ul><div class='small'>Advisory only. These signals describe input quality, not compliance; they never change any status.</div></div>")
    overview = f"""
<div class="card top">{gauge}<div style="flex:1;min-width:220px"><h2>Vendor: {_esc(a.vendor)}</h2>
<div class="small">Readiness: {pct}% of evaluated questions established or partial ({ev_n} evaluated)</div>
<div class="meta"><span class="tag t-mode">MODE: {_esc(a.mode)}</span><span class="chip">{len(a.documents)} file(s) analysed</span></div>
<details class="fileline"><summary>Show files</summary><div>{docs_chips}</div></details></div></div>
<div class="card">{dist}{legend}</div>
{health_card}
{_what_changed_card(request, a)}
{key_findings}{gaps_table}
{_contradiction_block(a)}
{mode_note}{errors}
<div class="card"><strong>Semantic analysis status:</strong> {_esc(semantic_label)}<div class="small">Deterministic extraction is reported separately and is never presented as semantic analysis.</div></div>"""
    questions_panel = f"""
<div class="strip nop">{strip}</div>
{section(CONFLICT, "Conflicting evidence")}
{section(CLARIFICATION, "Clarification required")}
{section(PARTIAL, "Partially established")}
{section(ESTABLISHED, "Established")}
{section(NOT_ESTABLISHED, "No supported fact found for evaluated requirements")}
{section(NOT_EVALUATED, "Not evaluated at runtime")}"""
    details_panel = f"""
<details class="fold" open><summary>Assessment overview</summary><div class="cards">{cards}</div></details>
<details class="fold"><summary>Analysis diagnostics</summary>{diagnostics}</details>
{('<details class="fold"><summary>Evidence QA</summary>' + evidence_block + '</details>') if evidence_block else ''}
{('<details class="fold"><summary>BCP / DR / Backup</summary>' + recovery_block + '</details>') if recovery_block else ''}
{('<details class="fold"><summary>Cross-artifact evidence graph</summary>' + graph_block + '</details>') if graph_block else ''}
{('<details class="fold"><summary>Unsupported questions</summary>' + unsupported_section + '</details>') if unsupported_section else ''}
<details class="fold"><summary>How to read this assessment &amp; disclaimer</summary>{guide}
<p class="disclaimer">DriftGuard produces readiness signals only. Missing material
is not a control failure, and a policy statement is not evidence of operating
effectiveness. Nothing here is a SOC 2 compliance conclusion, audit opinion, or
certification.</p></details>"""
    tab_items = [
        ("t-overview", "Overview", None, overview),
        ("t-questions", "Questions", len(implemented), questions_panel),
    ]
    if follow_form:
        tab_items.append(("t-clarify", "Needs your input", n_follow, follow_form))
    tab_items.append(("t-details", "Evidence &amp; details", None, details_panel))
    return _page(f"DriftGuard results: {a.vendor}", f"""
{_tabs(tab_items)}
<div class="actions nop"><a class="pill" href="/assessment?vendor={_esc(a.vendor)}">Answer full questionnaire manually</a>
{(f'<a class="pill" href="/export/{_esc(a.assessment_id)}">Export JSON report</a> <a class="pill" href="/export-pdf/{_esc(a.assessment_id)}">Download PDF</a>' if request is None or _user_id(request) is not None else '<a class="pill" href="/register">Create account to save &amp; export</a>')}<a class="pill" href="/">Start over</a></div>""")


def _gap_view_for(assessment_id: str, request):
    if request is not None and _auth_required() and _user_id(request) is None:
        return None, JSONResponse({'error': 'create an account to use reports and exports'}, status_code=403)
    a = _owned_get(DOC_ASSESSMENTS, "doc-results", assessment_id, request)
    if a is None:
        return None, JSONResponse({"error": "Unknown assessment"}, status_code=404)
    from documents import QUESTION_SPECS
    from evidence.gap_view import build_gap_view
    return (a, build_gap_view([x for x in a.areas if x.question_id in QUESTION_SPECS], a.extraction)), None


@app.get("/gaps/{assessment_id}", response_class=HTMLResponse)
def gaps_request_page(assessment_id: str, request: Request = None):
    got, err = _gap_view_for(assessment_id, request)
    if err is not None:
        return err
    from evidence.gap_view import render_request_page
    a, view = got
    return HTMLResponse(render_request_page(view, a.vendor, a.assessment_id))


@app.get("/gaps-csv/{assessment_id}")
def gaps_csv_export(assessment_id: str, request: Request = None):
    got, err = _gap_view_for(assessment_id, request)
    if err is not None:
        return err
    from evidence.gap_view import gaps_csv
    a, view = got
    return Response(gaps_csv(view), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="evidence-request-{a.assessment_id}.csv"'})



@app.get("/export/{assessment_id}")
def export_assessment(assessment_id: str, request: Request = None):
    if request is not None and _auth_required() and _user_id(request) is None:
        return JSONResponse({'error':'create an account to use reports and exports'}, status_code=403)
    a = _owned_get(DOC_ASSESSMENTS, "doc-results", assessment_id, request)
    if a is None:
        return JSONResponse({"error": "Unknown assessment"}, status_code=404)
    payload = {
        "assessment_id": a.assessment_id, "vendor": a.vendor, "mode": a.mode,
        "semantic_status": a.semantic_status, "semantic_rejections": a.semantic_rejections, "semantic_conflicts": list(a.semantic_conflicts), "files_received": a.files_received or len(a.documents),
        "files_parsed": len(a.documents), "documents": list(a.documents), "errors": list(a.errors),
        "counts": a.counts, "contract_coverage": a.contract_coverage,
        "extraction": list(a.extraction), "run_stamp": dict(a.run_stamp),
        "explainability": __import__("evidence.report", fromlist=["build_question_reports"]).build_question_reports(a.areas, a.extraction),
        "questions": [{
            "questionnaire_id": x.questionnaire_id, "question_id": x.question_id, "area": x.area,
            "question": x.question, "status": x.status, "why": x.reason,
            "known_facts": [{"label": f.label, "statement": f.statement, "filename": f.source_file,
                              "locator": f.source_locator, "excerpt": f.snippet,
                              "extraction_method": f.extraction_method, "artifact_type": f.artifact_type,
                              "source_role": f.source_role} for f in x.known_facts],
            "unknown_facts": list(x.missing_facts), "evidence_needed": list(x.evidence_needed),
        } for x in a.areas],
        "evidence_qa": [e.to_dict() for e in a.evidence],
        "cross_artifact": ([{
            "code": o.code, "state": o.state, "relationship": o.relationship, "detail": o.detail,
            "provenance": [{"filename": p.filename, "sheet": p.sheet, "locator": p.locator, "excerpt": p.excerpt} for p in o.provenance]
        } for o in a.evidence_graph.observations] if a.evidence_graph else []),
        "recovery": ({"issues": [{"code": i.code, "state": i.state, "detail": i.detail,
            "provenance": [{"filename": p.filename, "locator": p.locator, "excerpt": p.excerpt} for p in i.provenance]} for i in a.recovery.issues]} if a.recovery else {}),
        "disclaimer": "Readiness evidence analysis only; not a SOC 2 compliance conclusion, audit opinion, or certification.",
    }
    import json as _json
    body = _json.dumps(payload, indent=2, ensure_ascii=False)
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="driftguard-{a.assessment_id}.json"'
    })


@app.get("/export-pdf/{assessment_id}")
def export_pdf(assessment_id: str, request: Request = None):
    if request is not None and _auth_required() and _user_id(request) is None:
        return JSONResponse({'error':'create an account to use reports and exports'}, status_code=403)
    a = _owned_get(DOC_ASSESSMENTS, "doc-results", assessment_id, request)
    if a is None:
        return JSONResponse({"error": "Unknown assessment"}, status_code=404)
    from fpdf import FPDF
    from documents import QUESTION_SPECS

    def t(s) -> str:  # core PDF fonts are latin-1 only
        return str(s).encode("latin-1", "replace").decode("latin-1")

    implemented = [x for x in a.areas if x.question_id in QUESTION_SPECS]
    good = sum(x.status in (ESTABLISHED, PARTIAL) for x in implemented)
    ev_n = sum(x.status in (ESTABLISHED, PARTIAL, NOT_ESTABLISHED, CLARIFICATION, CONFLICT) for x in implemented)
    pct = round(100 * good / ev_n) if ev_n else 0
    sev = {CONFLICT: 0, CLARIFICATION: 1, NOT_ESTABLISHED: 2, PARTIAL: 3}
    gaps = sorted((x for x in implemented if x.status in sev), key=lambda x: sev[x.status])

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def h(text, size=13):
        pdf.set_font("Helvetica", "B", size)
        pdf.multi_cell(0, 7, t(text), new_x="LMARGIN", new_y="NEXT")

    def p(text, size=10, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, 5, t(text), new_x="LMARGIN", new_y="NEXT")

    h("DriftGuard SOC 2 Readiness Report", 16)
    p(f"Vendor: {a.vendor}    Assessment: {a.assessment_id}")
    pdf.ln(2)
    h(f"Readiness score: {pct}%")
    p(f"{good} of {ev_n} evaluated questions established or partial.")
    pdf.ln(2)
    h(f"Gaps to close ({len(gaps)})")
    for x in gaps:
        p(f"{x.area} - {x.status.replace('_', ' ')}", style="B")
        p("Evidence needed: " + ("; ".join(x.evidence_needed) or "-"))
        pdf.ln(1)
    pdf.ln(2)
    h("Per-question evidence")
    for x in a.areas:
        p(f"{x.question_id}: {x.question} [{x.status.replace('_', ' ')}]", style="B")
        if not x.known_facts:
            p("No supporting evidence found in the uploaded files.")
        for f in x.known_facts:
            loc = f" ({f.source_locator})" if f.source_locator else ""
            p(f"- {f.statement}  Source: {f.source_file}{loc}")
        pdf.ln(1)
    pdf.ln(3)
    p("Readiness evidence analysis only; not a SOC 2 compliance conclusion, audit opinion, or certification.", 9, "I")
    return Response(bytes(pdf.output()), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="driftguard-{a.assessment_id}.pdf"'
    })


_EVIDENCE_TAGS = {"SUPPORTED": "t-ok", "PARTIALLY_SUPPORTED": "t-rev",
                  "MISSING": "t-skip", "CONFLICT": "t-gap", "NEEDS_REVIEW": "t-rev"}
_DISAGREES_TAG = "<span class='tag t-gap'>disagrees</span>"


def _report_lines(lines, empty: str) -> str:
    """One card per check: plain headline, exact provenance, trace label beneath."""
    if not lines:
        return f"<div class='card small'>{_esc(empty)}</div>"
    return "".join(
        f"<div class='card'>"
        f"<span class='tag {_EVIDENCE_TAGS.get(x.state, 't-skip')}'>"
        f"{_esc(x.state_word)}</span> <strong>{_esc(x.headline)}</strong>"
        + ("".join(f"<div class='small'>source: {_esc(str(p))}"
                   + (f" &mdash; &ldquo;{_esc(p.excerpt)}&rdquo;" if p.excerpt else "")
                   + "</div>" for p in x.provenance[:6]) or "")
        + (f"<div class='small'>&hellip; and {len(x.provenance) - 6} more cell "
           f"references</div>" if len(x.provenance) > 6 else "")
        + f"<div class='qid'>{_esc(x.name)} &middot; {_esc(x.check_id)}"
        + (f" &middot; {_esc(x.grounding)}" if x.grounding else "")
        + "</div></div>"
        for x in lines
    )


def _evidence_report(e) -> str:
    """Evidence QA exception report for one artifact (presentation only)."""
    r = build_report(e)
    if not r.reconciled and not r.exceptions:
        return (f"<div class='card'><strong>{_esc(r.filename)}</strong> "
                f"<span class='tag t-skip'>{_esc(r.evidence_type)}</span>"
                f"<div><strong>Recognized artifact type:</strong> {_esc(r.evidence_type)}</div>"
                f"<div><strong>Validator used:</strong> {_esc(r.extractor or 'none / unclassified')}</div>"
                f"<div><strong>Classification confidence:</strong> {e.classification_confidence:.2f}</div>"
                f"<div><strong>Signals / canonical mapping:</strong> {_esc('; '.join(e.matched_signals)) if e.matched_signals else 'none'}</div>"
                f"<div><strong>Checks performed:</strong> none recorded</div>"
                f"<div><strong>Checks not performed / limitations:</strong> {_esc('; '.join(r.notes)) if r.notes else 'No type-specific checks were recorded.'}</div>"
                f"<div><strong>Facts extracted:</strong> {len(r.facts)}</div><div><strong>Exceptions:</strong> 0</div>"
                f"<div class='small'><strong>Interpretation:</strong> classification identifies the artifact schema; it does not by itself mean validation passed. Zero exceptions is not a control conclusion.</div>"
                + "</div>")

    meta = " &middot; ".join(filter(None, [
        f"review period {_esc(r.review_period)}" if r.review_period else "",
        f"campaign {_esc(r.campaign_status)}" if r.campaign_status else "",
        f"knowledge {_esc(r.knowledge_evidence_id)}" if r.knowledge_evidence_id else "",
        f"read by {_esc(r.extractor)}" if r.extractor else "",
    ]))
    facts = "".join(
        f"<tr><td>{_esc(f.label)}<div class='qid'>{_esc(f.key)}</div></td>"
        f"<td>{_DISAGREES_TAG if f.conflict else _esc(fact_display(f))}"
        + ("".join(f"<div class='small'>{_esc(v)} &mdash; {_esc(str(p))}</div>"
                   for v, p in f.conflicting_values) if f.conflict else "")
        + f"</td><td class='small'>{_esc(f.derivation)}</td>"
        f"<td class='small'>"
        + "".join(f"<div>{_esc(str(p))}</div>" for p in f.provenance)
        + "</td></tr>"
        for f in r.facts
    )
    checks_performed = [x.name for x in (list(r.reconciled) + list(r.exceptions))]
    checks_not_performed = list(r.notes) or (["No additional type-specific check was recorded by this validator."] if not checks_performed else [])
    return f"""
<div class="card"><h2 style="margin-top:0">{_esc(r.filename)}</h2>
<div><strong>Recognized artifact type:</strong> {_esc(r.evidence_type)}</div>
<div><strong>Validator used:</strong> {_esc(r.extractor or 'none / unclassified')}</div>
<div><strong>Classification confidence:</strong> {e.classification_confidence:.2f}</div>
<div><strong>Signals / canonical mapping:</strong> {_esc('; '.join(e.matched_signals)) if e.matched_signals else 'none'}</div>
<div><strong>Checks performed:</strong> {_esc('; '.join(checks_performed)) if checks_performed else 'none recorded'}</div>
<div><strong>Checks not performed / limitations:</strong> {_esc('; '.join(checks_not_performed)) if checks_not_performed else 'none recorded'}</div>
<div><strong>Facts extracted:</strong> {len(r.facts)}</div>
<div><strong>Exceptions:</strong> {r.exception_count}</div>
<span class="tag t-mode">{_esc(r.evidence_type)}</span>
<span class="tag {_EVIDENCE_TAGS.get(r.state, 't-skip')}">{_esc(r.state.replace('_', ' '))}</span>
<span class="tag {'t-gap' if r.exception_count else 't-ok'}">
{r.exception_count} item(s) to look at</span>
<div class="small">{meta}</div>
<div class="small"><strong>Interpretation:</strong> classification identifies the artifact schema; it does not by itself mean validation passed. Zero exceptions is not a control conclusion.</div></div>
<h2>Needs attention ({r.exception_count})</h2>
{_report_lines(r.exceptions, NO_EXCEPTIONS)}
<h2>Reconciled ({len(r.reconciled)})</h2>
{_report_lines(r.reconciled, "No check reconciled from this artifact.")}
<details><summary class="small">Facts read from this artifact ({len(r.facts)})</summary>
<table><tr><th>Fact</th><th>Value</th><th>Read as</th><th>Provenance</th></tr>
{facts}</table></details>"""


def _evidence_block(a: DocumentAssessment) -> str:
    if not a.evidence:
        return ""
    return ("<h2>Evidence QA</h2><p class='small'>What an auditor would ask about "
            "this artifact first. Every line is reconciled by DriftGuard arithmetic "
            "against the artifact's own numbers; missing material is reported as "
            "missing evidence, never as a control failure, and nothing here is a "
            "compliance conclusion.</p>"
            + "".join(_evidence_report(e) for e in a.evidence))


@app.get("/evidence-report/{assessment_id}", response_class=HTMLResponse)
def evidence_report(assessment_id: str, request: Request = None) -> HTMLResponse:
    if request is not None and _auth_required() and _user_id(request) is None:
        return JSONResponse({'error':'create an account to use reports and exports'}, status_code=403)
    """Standalone Evidence QA report - the page a compliance lead reviews."""
    a = _owned_get(DOC_ASSESSMENTS, "doc-results", assessment_id, request)
    if a is None:
        return _page("Not found", "<div class='card'>Unknown assessment. "
                                  "<a href='/'>Start again</a>.</div>", 404)
    body = (_evidence_block(a) or
            "<div class='card'>No tabular evidence was uploaded with this "
            "assessment.</div>")
    return _page(f"Evidence QA: {a.vendor}", f"""
<div class="card"><h2 style="margin-top:0">Evidence QA &mdash; {_esc(a.vendor)}</h2>
<span class="small">assessment {_esc(a.assessment_id)}</span></div>
{body}
<p class="disclaimer">DriftGuard reports what an artifact does and does not
evidence about itself. It is not a SOC 2 compliance conclusion, audit opinion, or
certification.</p>
<p><a href="/doc-results/{_esc(a.assessment_id)}">Back to document analysis</a>
&middot; <a href="/">Start over</a></p>""")


@app.post("/clarify/{assessment_id}")
async def clarify(assessment_id: str, request: Request):
    a = _owned_get(DOC_ASSESSMENTS, "doc-results", assessment_id, request)
    if a is None:
        return JSONResponse({"error": "Unknown assessment"}, status_code=404)
    vendor = a.vendor
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
    _bind_owner("results", result.assessment_id, request)
    return RedirectResponse(f"/results/{result.assessment_id}", status_code=303)


def _question_form(vendor: str) -> HTMLResponse:
    steps = []
    for doc in KNOWLEDGE.questionnaires:
        qn_id = doc["questionnaire_id"]
        for q in doc["questions"]:
            name = f"{qn_id}|{q['question_id']}"
            steps.append(
                f"<section class='step' data-group='{_esc(qn_id)} — {_esc(doc['name'])}'>"
                f"<div class='qid'>{_esc(q['question_id'])} &middot; {_esc(q['answer_type'])} "
                f"&middot; {', '.join(_esc(c) for c in doc['covers_criteria'])}</div>"
                f"<h3 class='qtext'>{_esc(q['text'])}</h3>"
                f"{_control(name, q, 'Free-text answer')}</section>"
            )
    hidden = f"<input type='hidden' name='vendor' value='{_esc(vendor)}'>"
    return _page("DriftGuard assessment", f"""
<div class="card"><strong>Vendor:</strong> {_esc(vendor)}
<span class="tag t-mode">MODE: {_mode_label()}</span>
<p class="small" style="margin:6px 0 0">Leave a question blank to skip it. One question at a time &mdash; tap an answer to continue.</p></div>
<div class="card">{_wizard('/run', steps, 'Run Assessment', hidden)}</div>""")


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
    _bind_owner("results", result.assessment_id, request)
    return RedirectResponse(f"/results/{result.assessment_id}", status_code=303)


@app.get("/results/{assessment_id}", response_class=HTMLResponse)
def results(assessment_id: str, request: Request = None) -> HTMLResponse:
    a = _owned_get(ASSESSMENTS, "results", assessment_id, request)
    if a is None:
        return _page("Not found", "<div class='card'>Unknown assessment. "
                                  "<a href='/'>Start again</a>.</div>", 404)
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
            f"<tr><td data-l='Question'><div class='qid'>{_esc(r.question_id)}</div>{_esc(r.text)}"
            f"<div class='small'>answer: {_esc(answer[:240])}</div></td>"
            f"<td data-l='Mode'>{_esc(r.mode)}</td><td data-l='Status'>{tag}<div class='small'>{_esc(r.detail)}</div></td>"
            f"<td data-l='Semantic verdict'>{semantic}</td><td data-l='Observation / remediation'>{findings}</td></tr>"
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
<table class="rt"><thead><tr><th>Question</th><th>Mode</th><th>Status</th><th>Semantic verdict</th>
<th>Observation / remediation</th></tr></thead><tbody>{''.join(rows) or
  "<tr><td colspan='5'>No questions were answered.</td></tr>"}</tbody></table>
<p class="disclaimer">DriftGuard produces readiness signals only. Nothing here is a
SOC 2 compliance conclusion, audit opinion, or certification. Items marked NEEDS
REVIEW require human judgement.</p>
<p><a href="/">Start another assessment</a></p>""")


# ---------------------------------------------------------------------------
# Accounts + per-user persistence (SQLite). Anonymous use of every route above
# keeps working; assessments created while logged in are saved and reopenable.
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402
import hmac  # noqa: E402
import os  # noqa: E402
import json  # noqa: E402
import dataclasses  # noqa: E402
import importlib  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
from driftguard_platform.config import PlatformConfig  # noqa: E402
from driftguard_platform.persistence.accounts import DuplicateUserError  # noqa: E402
from driftguard_platform.persistence.repositories import create_account_repository  # noqa: E402
import time  # noqa: E402
from collections import defaultdict, deque  # noqa: E402

_COOKIE = "dg_session"
_SAVED_PATH = re.compile(r"^/(doc-results|results)/([^/?#]+)")
_STORES = {"doc-results": DOC_ASSESSMENTS, "results": ASSESSMENTS}


def _accounts():
    """Configured identity/session/history repository; domain logic is storage-agnostic."""
    return create_account_repository(PlatformConfig.from_env())


def _hash_pw(password: str, salt: bytes | None = None, iterations: int = 600_000) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def _check_pw(password: str, stored: str) -> bool:
    try:
        if stored.startswith("pbkdf2_sha256$"):
            _, rounds, salt_hex, digest = stored.split("$", 3)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)).hex()
            return hmac.compare_digest(actual, digest)
        # Backward compatibility for pre-hardening 200k hashes. Login upgrades them.
        salt_hex, digest = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


_SAFE_STATE_MODULES = {"assessment", "documents", "evidence.model", "evidence.graph", "bcp_dr", "narrative_intelligence", "policy_conflicts"}

_SRC_DIR = Path(__file__).resolve().parent

def _state_module_allowed(module_name: str) -> bool:
    """Allow explicit modules plus first-party modules inside src/ (never stdlib/third-party)."""
    if module_name in _SAFE_STATE_MODULES:
        return True
    parts = module_name.split(".")
    if not all(p.isidentifier() for p in parts):
        return False
    base = _SRC_DIR.joinpath(*parts)
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()

def _state_encode(value):
    if dataclasses.is_dataclass(value):
        return {"__type__": f"{value.__class__.__module__}.{value.__class__.__name__}",
                "fields": {f.name: _state_encode(getattr(value, f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value, tuple): return {"__tuple__": [_state_encode(v) for v in value]}
    if isinstance(value, list): return [_state_encode(v) for v in value]
    if isinstance(value, dict): return {str(k): _state_encode(v) for k, v in value.items()}
    if isinstance(value, (date, datetime)): return {"__date__": value.isoformat(), "datetime": isinstance(value, datetime)}
    if value is None or isinstance(value, (str, int, float, bool)): return value
    raise TypeError(f"Unsupported saved-state type: {type(value).__name__}")

def _state_decode(value):
    if isinstance(value, list): return [_state_decode(v) for v in value]
    if not isinstance(value, dict): return value
    if "__tuple__" in value: return tuple(_state_decode(v) for v in value["__tuple__"])
    if "__date__" in value:
        return datetime.fromisoformat(value["__date__"]) if value.get("datetime") else date.fromisoformat(value["__date__"])
    if "__type__" in value:
        module_name, _, class_name = value["__type__"].rpartition(".")
        if not _state_module_allowed(module_name):
            raise ValueError("Saved-state type is not allowed")
        cls = getattr(importlib.import_module(module_name), class_name, None)
        if cls is None or not dataclasses.is_dataclass(cls):
            raise ValueError("Saved-state class is not allowed")
        return cls(**{k: _state_decode(v) for k, v in value.get("fields", {}).items()})
    return {k: _state_decode(v) for k, v in value.items()}

def _serialize_state(obj) -> str:
    return json.dumps(_state_encode(obj), separators=(",", ":"), ensure_ascii=False)

def _deserialize_state(blob):
    if isinstance(blob, bytes): blob = blob.decode("utf-8")
    return _state_decode(json.loads(blob))

def _user_id(request: Request):
    token = request.cookies.get(_COOKIE) if request is not None else None
    if not token:
        return None
    return _accounts().user_for_session(token, datetime.now(timezone.utc).isoformat())


def _auth_required() -> bool:
    return os.getenv("DRIFTGUARD_REQUIRE_AUTH", "1").strip().lower() not in {"0", "false", "no"}

def _principal(request: Request) -> str | None:
    uid = _user_id(request)
    if uid is not None:
        return f'user:{uid}'
    guest = request.cookies.get(_GUEST_COOKIE) if request is not None else None
    return f'guest:{guest}' if guest else None

def _bind_owner(kind: str, aid: str, request: Request) -> None:
    principal = _principal(request)
    if principal is not None:
        _ASSESSMENT_OWNERS[(kind, aid)] = principal

def _load_own_saved(kind: str, aid: str, principal: str):
    """Rehydrate the caller's own saved, non-deleted assessment after a restart or cache eviction."""
    if not principal.startswith('user:'):
        return None
    uid = int(principal.split(':', 1)[1])
    blob = _accounts().load_saved(uid, kind, aid)   # scoped by user_id and deleted_at IS NULL
    if blob is None:
        return None
    try:
        obj = _deserialize_state(blob)
    except (ValueError, TypeError, KeyError, AttributeError, ImportError):
        return None
    _STORES[kind][aid] = obj
    _ASSESSMENT_OWNERS[(kind, aid)] = principal
    return obj


def _owned_get(store, kind: str, aid: str, request: Request):
    obj = store.get(aid)
    if not _auth_required():
        return obj
    principal = _principal(request)
    if principal is None:
        return None
    owner = _ASSESSMENT_OWNERS.get((kind, aid))
    if obj is None:
        return _load_own_saved(kind, aid, principal)
    if owner is None and principal.startswith('user:'):
        uid = int(principal.split(':',1)[1])
        if _accounts().saved_exists(uid, kind, aid):
            _ASSESSMENT_OWNERS[(kind, aid)] = principal
            return obj
        return None
    return obj if owner is not None and hmac.compare_digest(str(owner), principal) else None

_RATE_BUCKETS = defaultdict(deque)

def _rate_ok(key: str, limit: int, window: int) -> bool:
    now = time.monotonic(); q = _RATE_BUCKETS[key]
    while q and now - q[0] > window: q.popleft()
    if len(q) >= limit: return False
    q.append(now)
    if len(_RATE_BUCKETS) > 10000:
        for k in list(_RATE_BUCKETS)[:1000]:
            if not _RATE_BUCKETS[k]: _RATE_BUCKETS.pop(k, None)
    return True

_PROTECTED_POSTS = {"/analyze", "/analyze-sample", "/assessment", "/run", "/api/evidence-map", "/jobs"}

@app.middleware("http")
async def _security_boundary(request: Request, call_next):
    try:
        _NAV.set(_NAV_USER if _user_id(request) is not None
                 else _NAV_GUEST if request.cookies.get(_GUEST_COOKIE) else _NAV.get())
    except Exception:
        pass
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_TOTAL_BYTES + 1024 * 1024:
        return JSONResponse({"error": "request body too large"}, status_code=413)
    if request.url.path == "/login" and request.method == "POST":
        ip = request.client.host if request.client else "unknown"
        if not _rate_ok(f"login:{ip}", 10, 300):
            return JSONResponse({"error": "too many login attempts"}, status_code=429)
    if _auth_required():
        protected = request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
            request.url.path in _PROTECTED_POSTS or request.url.path.startswith(("/clarify/", "/jobs/"))
        ) or request.url.path.startswith("/api/v1/")
        uid = _user_id(request)
        api_key_ok = False
        if request.url.path == "/api/evidence-map":
            configured = os.getenv("DRIFTGUARD_API_KEY", "")
            supplied = request.headers.get("x-driftguard-api-key", "")
            api_key_ok = bool(configured and hmac.compare_digest(configured, supplied))
        if protected and request.url.path not in {"/login", "/register"} and uid is None and not api_key_ok:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"error": "authentication required"}, status_code=401)
            next_path = request.url.path
            return RedirectResponse(f"/login?next={quote(next_path, safe='/')}", status_code=303)
        if protected and uid is not None and not _rate_ok(f"work:{uid}", 60, 60):
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
                if origin.rstrip("/") != expected.rstrip("/"):
                    return JSONResponse({"error": "cross-site request rejected"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return response

@app.middleware("http")
async def _persist_assessments(request: Request, call_next):
    uid = _user_id(request)
    m = _SAVED_PATH.match(request.url.path)
    if uid and m and request.method == "GET" and _STORES[m.group(1)].get(m.group(2)) is None:
        blob = _accounts().load_saved(uid, m.group(1), m.group(2))
        if blob is not None:
            try:
                _STORES[m.group(1)][m.group(2)] = _deserialize_state(blob)
                _ASSESSMENT_OWNERS[(m.group(1), m.group(2))] = f'user:{uid}'
            except (ValueError, TypeError, KeyError, AttributeError, ImportError):
                pass  # unreadable saved state: treat as not found instead of a 500
    response = await call_next(request)
    m = _SAVED_PATH.match(response.headers.get("location", ""))
    if uid and m and response.status_code in (302, 303):
        obj = _STORES[m.group(1)].get(m.group(2))
        if obj is not None:
            label = str(getattr(obj, "vendor", "") or getattr(obj, "vendor_name", "") or "Assessment")
            _accounts().save_bounded(uid, m.group(1), m.group(2), label, _serialize_state(obj), limit=100)
    return response


@app.middleware("http")
async def _request_context(request: Request, call_next):
    """Outermost: request/assessment ids on every log line, and one access line per request (no query string)."""
    rid = new_request_id(request.headers.get("x-request-id"))
    request_id_var.set(rid)
    assessment_id_var.set(assessment_id_from_path(request.url.path))
    t0 = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        log_event("request_failed", code=ErrorCode.INTERNAL, level=logging.ERROR, method=request.method,
                  path=request.url.path, error_type=type(exc).__name__,
                  duration_ms=round((time.monotonic() - t0) * 1000))
        raise
    response.headers["X-Request-ID"] = rid
    fields = {} if response.status_code < 400 else {"code": code_for_status(response.status_code)}
    log_event("request", method=request.method, path=request.url.path, status=response.status_code,
              duration_ms=round((time.monotonic() - t0) * 1000), **fields)
    return response


def _what_changed_card(request: Request, a) -> str:
    """Compare against the user's previous saved run for the same company (needs login/history)."""
    uid = _user_id(request)
    if not uid:
        return ""
    prev_blob = _accounts().previous_saved_blob(uid, "doc-results", a.assessment_id, str(a.vendor))
    if not prev_blob:
        return ""
    try:
        old = {x.question_id: x for x in _deserialize_state(prev_blob).areas}
    except (ValueError, TypeError, KeyError, AttributeError, ImportError):
        return ""
    rank = {ESTABLISHED: 2, PARTIAL: 1}
    improved, regressed, still_open = [], [], []
    for x in a.areas:
        o = old.get(x.question_id)
        if o is None or x.status == NOT_EVALUATED or o.status == NOT_EVALUATED:
            continue
        line = f"{_esc(x.area)}: {_esc(o.status.replace('_', ' '))} &rarr; {_esc(x.status.replace('_', ' '))}"
        if rank.get(x.status, 0) > rank.get(o.status, 0):
            improved.append(line)
        elif rank.get(x.status, 0) < rank.get(o.status, 0):
            regressed.append(line)
        elif x.status != ESTABLISHED:
            still_open.append(f"{_esc(x.area)}: {_esc(x.status.replace('_', ' '))}")

    def block(title: str, items: list[str]) -> str:
        if not items:
            return f"<div class='small' style='padding:8px 12px'>{title} (0)</div>"
        lis = "".join(f"<li>{i}</li>" for i in items)
        return f"<details><summary>{title} ({len(items)})</summary><ul>{lis}</ul></details>"

    return ("<div class='card' id='what-changed'><h2 style='margin-top:0'>What changed</h2>"
            "<div class='small'>Versus your previous run for this company.</div><div class='chg' style='margin-top:10px'>"
            + block("Improved", improved) + block("Regressed", regressed)
            + block("Still open", still_open) + "</div></div>")


def _safe_next(value: str | None) -> str:
    value = (value or "").strip()
    return value if value.startswith("/") and not value.startswith("//") else "/my-assessments"

_AUTH_CSS = """<style>
.auth{max-width:440px;margin:28px auto}.auth .card{padding:28px 26px}
.auth h2{margin:0 0 4px;font-size:24px;letter-spacing:-.02em}.auth .sub{color:var(--mut);font-size:14px;margin:0 0 20px}
.auth label{display:block;font-size:13px;font-weight:600;margin:14px 0 6px}
.auth input[type=email],.auth input[type=password]{width:100%;box-sizing:border-box;padding:12px 14px;border:1.5px solid var(--line);border-radius:12px;font:inherit;background:var(--card);color:var(--ink)}
.auth input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 22%,transparent)}
.auth .hint{font-size:12px;color:var(--mut);margin-top:5px}.auth .err{background:color-mix(in srgb,#ef4444 12%,transparent);border:1px solid #ef4444;color:var(--ink);padding:10px 12px;border-radius:10px;font-size:13px;margin-bottom:6px}
.auth .btn-main{width:100%;margin-top:20px;padding:13px}.auth .alt{text-align:center;font-size:14px;margin-top:16px;color:var(--mut)}
.auth .alt a{color:var(--acc);font-weight:600;text-decoration:none}.auth .or{display:flex;align-items:center;gap:10px;color:var(--mut);font-size:12px;margin:22px 0 14px}
.auth .or::before,.auth .or::after{content:'';flex:1;height:1px;background:var(--line)}.auth .guest{width:100%}
</style>"""


def _auth_form(kind: str, error: str = "", next_path: str = "") -> HTMLResponse:
    reg = kind == "register"
    title, sub = ("Create your account", "Save assessments, exports and history in a private workspace.") if reg else ("Welcome back", "Sign in to your DriftGuard workspace.")
    err = f"<div class='err' role='alert'>{_esc(error)}</div>" if error else ""
    hint = "<div class='hint'>At least 8 characters.</div>" if reg else ""
    ac = "new-password" if reg else "current-password"
    alt = ("Already have an account? <a href='/login'>Sign in</a>" if reg
           else "New to DriftGuard? <a href='/register'>Create an account</a>")
    return _page(title, (
        f"{_AUTH_CSS}<div class='auth'><div class='card'><h2>{title}</h2><p class='sub'>{sub}</p>{err}"
        f"<form method='post' action='/{kind}'>"
        f"<input type='hidden' name='next' value='{_esc(_safe_next(next_path))}'>"
        "<label for='email'>Email</label><input id='email' name='email' type='email' placeholder='you@company.com' autocomplete='email' required>"
        f"<label for='password'>Password</label><input id='password' name='password' type='password' placeholder='Password' minlength='8' autocomplete='{ac}' required>{hint}"
        f"<button type='submit' class='btn-main'>{'Create account' if reg else 'Sign in'}</button></form>"
        f"<div class='alt'>{alt}</div>"
        "<div class='or'>or</div>"
        "<form method='post' action='/guest/start'><button type='submit' class='ghost guest'>Try as guest &mdash; no account needed</button></form>"
        "</div></div>"), 400 if error else 200)


async def _creds(request: Request):
    f = parse_qs((await request.body()).decode("utf-8", "replace"))
    return f.get("email", [""])[0].strip().lower(), f.get("password", [""])[0], _safe_next(f.get("next", [""])[0])


def _start_session(uid: int, next_path: str = "/my-assessments") -> RedirectResponse:
    token = secrets.token_urlsafe(32)
    _accounts().replace_session(uid, token, (datetime.now(timezone.utc)+timedelta(hours=8)).isoformat())
    r = RedirectResponse(_safe_next(next_path), status_code=303)
    r.set_cookie(_COOKIE, token, httponly=True, samesite="strict", secure=os.getenv("DRIFTGUARD_SECURE_COOKIES", "1" if os.getenv("DRIFTGUARD_ENV") == "production" else "0") == "1", max_age=8*60*60)
    return r


@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request) -> HTMLResponse:
    return _auth_form("register", next_path=request.query_params.get("next", ""))


@app.post("/register")
async def register_post(request: Request):
    email, pw, next_path = await _creds(request)
    if "@" not in email or len(pw) < 8:
        return _auth_form("register", "Enter a valid email and a password of 8+ characters.", next_path)
    try:
        uid = _accounts().create_user(email, _hash_pw(pw))
    except DuplicateUserError:
        return _auth_form("register", "That email is already registered.", next_path)
    return _start_session(uid, next_path)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request) -> HTMLResponse:
    return _auth_form("login", next_path=request.query_params.get("next", ""))


@app.post("/login")
async def login_post(request: Request):
    email, pw, next_path = await _creds(request)
    row = _accounts().find_user(email)
    if not row or not _check_pw(pw, row[1]):
        return _auth_form("login", "Invalid email or password.", next_path)
    if not row[1].startswith("pbkdf2_sha256$600000$"):
        _accounts().update_password(row[0], _hash_pw(pw))
    return _start_session(row[0], next_path)


@app.post("/logout")
def logout(request: Request):
    token = request.cookies.get(_COOKIE)
    if token:
        _accounts().delete_session(token)
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(_COOKIE)
    return r


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LIFECYCLE_ACTIONS = {"rename", "archive", "unarchive", "delete", "restore", "purge"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retention_days() -> int:
    """Days a soft-deleted item stays restorable before it is purged (DRIFTGUARD_RETENTION_DAYS, default 30)."""
    try:
        return max(0, int(os.getenv("DRIFTGUARD_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def _evict_saved(kind: str, aid: str, uid: int | None = None) -> None:
    """Drop in-memory state and stored uploads/checkpoints so a deleted/purged item cannot be served or recovered."""
    _STORES[kind].pop(aid, None)
    _ASSESSMENT_OWNERS.pop((kind, aid), None)
    if uid is not None:
        try:
            UPLOADS.delete(uid, aid)
        except (OSError, ValueError) as exc:
            log_event("upload_delete_failed", code=ErrorCode.STORAGE_FAILED, level=logging.ERROR, error_type=type(exc).__name__)


def _sweep_uploads(uid: int) -> None:
    """Remove upload directories whose saved row is gone (e.g. dropped by the per-user history cap)."""
    repo = _accounts()
    live = {r.aid for deleted in (False, True) for r in repo.list_saved(uid, deleted=deleted)}
    UPLOADS.sweep(uid, live)


def _purge_expired_saved() -> None:
    for _uid, kind, aid in _accounts().purge_expired(_now_iso(), _retention_days()):
        _evict_saved(kind, aid, _uid)


def _not_found() -> HTMLResponse:
    return _page("Not found", "<div class='card'><h2>Not found</h2><p><a href='/my-assessments'>Back to My assessments</a></p></div>", 404)


def _status_text(value: str) -> str:
    return _esc(str(value).replace("_", " "))


@app.get("/my-assessments", response_class=HTMLResponse)
def my_assessments(request: Request):
    uid = _user_id(request)
    if uid is None:
        return RedirectResponse("/login", status_code=303)
    _purge_expired_saved()
    _sweep_uploads(uid)
    qp = request.query_params
    trash = qp.get("view") == "trash"
    q = qp.get("q", "").strip()[:100]
    kind = qp.get("kind", "") if qp.get("kind", "") in _STORES else ""
    d_from = qp.get("from", "") if _DATE_RE.match(qp.get("from", "")) else ""
    d_to = qp.get("to", "") if _DATE_RE.match(qp.get("to", "")) else ""
    arch = qp.get("archived", "active")
    arch = arch if arch in {"active", "archived", "all"} else "active"
    repo = _accounts()
    rows = repo.list_saved(uid, query=q, kind=kind, date_from=d_from, date_to=d_to,
                           archived={"active": False, "archived": True, "all": None}[arch], deleted=trash)
    days = _retention_days()

    def btn(action, row, text, extra=""):
        return (f"<form method='post' action='/my-assessments/{action}' style='display:inline'>"
                f"<input type='hidden' name='kind' value='{_esc(row.kind)}'><input type='hidden' name='aid' value='{_esc(row.aid)}'>"
                f"{extra}<button type='submit' class='ghost'>{text}</button></form>")

    kind_name = {"doc-results": "Evidence assessment", "results": "Questionnaire"}

    def item(row):
        kn = _esc(kind_name.get(row.kind, row.kind))
        if trash:
            return (f"<li class='arow'><span></span><span class='nm'>{_esc(row.label)}<span class='sub'>{kn} &middot; deleted {_esc(row.deleted_at)} "
                    f"&middot; purged {days} days after deletion</span></span><span class='when'></span>"
                    f"<span class='acts'>{btn('restore', row, 'Restore')}{btn('purge', row, 'Delete permanently')}</span></li>")
        rename = f"<input name='label' value='{_esc(row.label)}' maxlength='200' aria-label='New name' required>"
        tag = " <span class='chip'>Archived</span>" if row.archived_at else ""
        rn = (f"<details><summary>Rename</summary><div class='rn'>"
              f"<form method='post' action='/my-assessments/rename' style='display:flex;gap:6px;flex:1'>"
              f"<input type='hidden' name='kind' value='{_esc(row.kind)}'><input type='hidden' name='aid' value='{_esc(row.aid)}'>"
              f"{rename}<button type='submit'>Save</button></form></div></details>")
        delete = btn('delete', row, 'Delete').replace("class='ghost'", "class='ghost danger'")
        return (f"<li class='arow'><input type='checkbox' form='cmp' name='pick' value='{_esc(row.kind)}:{_esc(row.aid)}' aria-label='Select for compare'>"
                f"<a class='nm' href='/{_esc(row.kind)}/{_esc(row.aid)}'>{_esc(row.label)}{tag}<span class='sub'>{kn}</span></a>"
                f"<span class='when small'>{_esc(row.created)}</span>"
                f"<span class='acts'>{rn}"
                f"{btn('unarchive' if row.archived_at else 'archive', row, 'Unarchive' if row.archived_at else 'Archive')}"
                f"{delete}</span></li>")

    filtered = bool(q or kind or d_from or d_to)
    items = "".join(item(r) for r in rows) or ("<li class='empty'>Nothing matches.</li>" if filtered else
                                               "<li class='empty'>Trash is empty.</li>" if trash else
                                               "<li class='empty'>No saved assessments yet. <a href='/'>Start one</a>.</li>")

    def sel(cur, val):
        return " selected" if cur == val else ""

    filters = (
        "<form method='get' action='/my-assessments' class='card toolbar'>"
        f"<input name='q' value='{_esc(q)}' placeholder='Search by name' aria-label='Search name'>"
        f"<select name='kind' aria-label='Kind'><option value=''>All types</option>"
        f"<option value='doc-results'{sel(kind, 'doc-results')}>Evidence assessment</option>"
        f"<option value='results'{sel(kind, 'results')}>Questionnaire</option></select>"
        f"<input type='date' name='from' value='{_esc(d_from)}' aria-label='From date'>"
        f"<input type='date' name='to' value='{_esc(d_to)}' aria-label='To date'>"
        f"<select name='archived' aria-label='Archived'><option value='active'{sel(arch, 'active')}>Active</option>"
        f"<option value='archived'{sel(arch, 'archived')}>Archived</option><option value='all'{sel(arch, 'all')}>All</option></select>"
        + ("<input type='hidden' name='view' value='trash'>" if trash else "")
        + "<button type='submit'>Filter</button></form>")
    switch = ("<a class='pill' href='/my-assessments'>&larr; Back to assessments</a>" if trash
              else "<a class='pill' href='/my-assessments?view=trash'>Trash</a><a class='pill' href='/'>+ New assessment</a>")
    compare = "" if trash else ("<div class='card cmpbar nop'><span class='small'>Tick two rows to compare runs.</span>"
                                "<form id='cmp' method='get' action='/my-assessments/compare'>"
                                "<button type='submit'>Compare two selected</button></form></div>")
    audit = "".join(f"<li><small>{_esc(a.at)} &middot; {_esc(a.action)} &middot; {_esc(a.kind)}/{_esc(a.aid)} {_esc(a.detail)}</small></li>"
                    for a in repo.list_audit(uid, 10)) or "<li><small>No activity yet.</small></li>"
    return _page("My assessments", (
        f"<div class='pg-head'><div><h2>{'Trash' if trash else 'My assessments'}</h2>"
        f"<p>{len(rows)} item(s)</p></div><div class='actions' style='margin:0'>{switch}</div></div>"
        f"{filters}<div class='card' style='padding:0'><ul class='alist'>{items}</ul></div>{compare}"
        f"<details class='fold'><summary>Recent activity</summary><ul class='small'>{audit}</ul></details>"))


@app.post("/my-assessments/{action}")
async def my_assessments_action(action: str, request: Request):
    """Owner-only lifecycle actions. Anything not owned by the caller is indistinguishable from missing (404)."""
    uid = _user_id(request)
    if uid is None:
        return RedirectResponse("/login", status_code=303)
    f = parse_qs((await request.body()).decode("utf-8", "replace"))
    kind, aid = f.get("kind", [""])[0], f.get("aid", [""])[0][:200]
    if action not in _LIFECYCLE_ACTIONS or kind not in _STORES or not aid:
        return _not_found()
    repo, now = _accounts(), _now_iso()
    if action == "rename":
        label = " ".join(f.get("label", [""])[0].split())[:200]
        if not label:
            return _page("Rename", "<div class='card'><h2>Name required</h2><p><a href='/my-assessments'>Back</a></p></div>", 400)
        ok = repo.rename_saved(uid, kind, aid, label, now)
    elif action in ("archive", "unarchive"):
        ok = repo.set_archived(uid, kind, aid, action == "archive", now)
    elif action == "delete":
        ok = repo.soft_delete_saved(uid, kind, aid, now)
    elif action == "restore":
        ok = repo.restore_saved(uid, kind, aid, now, _retention_days())
    else:
        ok = repo.purge_saved(uid, kind, aid, now)
    if not ok:
        repo.record_audit(uid, f"{action}.denied", kind, aid, now)
        return _not_found()
    if action in ("delete", "purge"):
        _evict_saved(kind, aid, uid)
    return RedirectResponse("/my-assessments", status_code=303)


@app.get("/my-assessments/compare", response_class=HTMLResponse)
def my_assessments_compare(request: Request):
    from assessment_compare import CompareUnsupported, compare_assessments
    uid = _user_id(request)
    if uid is None:
        return RedirectResponse("/login", status_code=303)
    picks = list(dict.fromkeys(request.query_params.getlist("pick")))
    if len(picks) != 2:
        return _page("Compare", "<div class='card'><h2>Select exactly two assessments</h2><p><a href='/my-assessments'>Back</a></p></div>", 400)
    repo, loaded = _accounts(), []
    for pick in picks:
        kind, _, aid = pick.partition(":")
        meta = repo.get_saved_meta(uid, kind, aid) if kind in _STORES and aid else None
        blob = repo.load_saved(uid, kind, aid) if meta else None
        if blob is None:
            repo.record_audit(uid, "compare.denied", kind[:40], aid[:200], _now_iso())
            return _not_found()
        try:
            loaded.append((meta, _deserialize_state(blob)))
        except (ValueError, TypeError, KeyError, AttributeError, ImportError):
            return _page("Compare", "<div class='card'><h2>Saved state is unreadable</h2></div>", 422)
    loaded.sort(key=lambda m: m[0].created)  # older run is the baseline
    (m1, o1), (m2, o2) = loaded
    try:
        cmp = compare_assessments(o1, o2)
    except CompareUnsupported as exc:
        return _page("Compare", f"<div class='card'><h2>Cannot compare</h2><p>{_esc(str(exc))}</p><p><a href='/my-assessments'>Back</a></p></div>", 422)
    repo.record_audit(uid, "compare", m1.kind, m1.aid, _now_iso(), f"with {m2.kind}/{m2.aid}")
    statuses = sorted(set(cmp.base_counts) | set(cmp.other_counts))
    counts = "".join(f"<tr><td>{_status_text(s)}</td><td>{cmp.base_counts.get(s, 0)}</td><td>{cmp.other_counts.get(s, 0)}</td></tr>" for s in statuses)

    def side(s):
        if s is None:
            return "<em>not present</em>"
        src = f"{_esc(s.source_file)} &middot; {_esc(s.source_locator)}" if (s.source_file or s.source_locator) else "no source recorded"
        snip = f"<br><small>{_esc(s.source_snippet)}</small>" if s.source_snippet else ""
        return f"{_status_text(s.status)}<br><small>{src}</small>{snip}"

    changed = [c for c in cmp.changes if c.change != "UNCHANGED"]
    rows = "".join(f"<tr><td>{_esc(c.question_id)}<br><small>{_esc(c.area)}</small></td><td>{_esc(c.change.title())}</td>"
                   f"<td>{side(c.base)}</td><td>{side(c.other)}</td></tr>" for c in changed) or "<tr><td colspan='4'>No status changes.</td></tr>"
    return _page("Compare assessments", (
        f"<div class='card'><h2>Compare assessments</h2><p><strong>Baseline:</strong> {_esc(m1.label)} <small>{_esc(m1.created)}</small><br>"
        f"<strong>Comparison:</strong> {_esc(m2.label)} <small>{_esc(m2.created)}</small></p>"
        f"<h3>Counts by status</h3><table><tr><th>Status</th><th>Baseline</th><th>Comparison</th></tr>{counts}</table>"
        f"<h3>Question changes</h3><p><small>{cmp.unchanged} question(s) unchanged. Observations only; no determination is made.</small></p>"
        f"<table><tr><th>Question</th><th>Change</th><th>Baseline</th><th>Comparison</th></tr>{rows}</table>"
        "<p><a href='/my-assessments'>Back to My assessments</a></p></div>"))

# ---------------------------------------------------------------------------
# Evidence-to-question audit trail (queryable per question, exportable).
@app.get("/audit-trail/{assessment_id}")
def audit_trail(assessment_id: str, request: Request = None):
    if request is not None and _auth_required() and _user_id(request) is None:
        return JSONResponse({'error': 'create an account to use reports and exports'}, status_code=403)
    a = _owned_get(DOC_ASSESSMENTS, "doc-results", assessment_id, request)
    if a is None:
        return JSONResponse({"error": "Unknown assessment"}, status_code=404)
    from evidence import audit_trail as at
    trail = at.build_audit_trail(a)
    qid = request.query_params.get("question", "") if request is not None else ""
    if qid:
        if qid not in {x.question_id for x in a.areas}:
            return JSONResponse({"error": "Unknown question"}, status_code=404)
        trail = at.for_question(trail, qid)
    if (request.query_params.get("format", "json") if request is not None else "json") == "csv":
        return Response(at.to_csv(trail), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="audit-trail-{a.assessment_id}.csv"'})
    return JSONResponse(trail)


# ---------------------------------------------------------------------------
# Background analysis job: stages with checkpoints, progress, per-stage timeouts.
import threading as _threading  # noqa: E402

_JOB_SLOTS = _threading.BoundedSemaphore(max(1, int(os.getenv("DRIFTGUARD_JOB_WORKERS", "2") or 2)))


def _job_stages() -> list:
    enc, dec = _state_encode, _state_decode

    def save_extract(c):
        return dict(documents=enc(c.documents), errors=list(c.errors), extraction=enc(c.extraction),
                    unique_sha=[r.sha256 for r in c.extraction if r.status != "DUPLICATE"])

    def load_extract(c, p):
        c.documents, c.errors, c.extraction = dec(p["documents"]), list(p["errors"]), dec(p["extraction"])
        want, c.payloads = set(p["unique_sha"]), []
        for name, data in c.payloads_in:
            d = hashlib.sha256(data).hexdigest()
            if d in want:
                want.discard(d)
                c.payloads.append((name, data))

    def save_map(c):
        return enc(c.result)

    def load_map(c, p):
        c.result = dec(p)
        c.result.assessment_id = c.assessment_id

    S = _jobs.Stage
    return [
        S("extract", _st_extract, save_extract, load_extract),
        S("classify", _st_classify, lambda c: c.classification, lambda c, p: c.classification.update(p)),
        S("validate", _st_validate, lambda c: enc(c.evidence), lambda c, p: setattr(c, "evidence", dec(p))),
        S("map", _st_map, save_map, load_map),
        S("sufficiency", _st_sufficiency, lambda c: c.sufficiency, lambda c, p: setattr(c, "sufficiency", p), required=False),
        S("report", _st_report, None, None, required=False),
    ]


def _job_view(uid: int, aid: str):
    """Status of a job owned by uid; the directory is keyed by owner, so another user's job simply does not exist."""
    try:
        job = _jobs.Job(UPLOADS.dir_for(uid, aid))
    except ValueError:
        return None
    st = job.status()
    return (job, st) if st else None


def _job_worker(uid: int, aid: str, rid: str) -> None:
    request_id_var.set(rid)
    assessment_id_var.set(aid)
    try:
        with _JOB_SLOTS:
            _job_worker_body(uid, aid)
    finally:
        with _jobs._ACTIVE_LOCK:
            _jobs.ACTIVE.discard(aid)


def _job_worker_body(uid: int, aid: str) -> None:
    job = _jobs.Job(UPLOADS.dir_for(uid, aid))
    try:
        payloads = UPLOADS.load(uid, aid)
    except (OSError, ValueError) as exc:
        rec = job.read()
        rec.update(state="failed", error_code=ErrorCode.STORAGE_FAILED.value)
        job.write(rec)
        log_event("job_stopped", code=ErrorCode.STORAGE_FAILED, level=logging.ERROR, error_type=type(exc).__name__)
        return
    ctx = _RunCtx(job.read().get("vendor", "Unnamed vendor"), payloads, assessment_id=aid)

    def finish(c):
        result = c.result
        DOC_ASSESSMENTS[aid] = result
        _ASSESSMENT_OWNERS[("doc-results", aid)] = f"user:{uid}"
        _accounts().save_bounded(uid, "doc-results", aid, str(result.vendor), _serialize_state(result), limit=100)
        try:
            _sweep_uploads(uid)
        except OSError:
            pass

    job.run(_job_stages(), ctx, on_complete=finish)


def _start_job(uid: int, aid: str, rid: str) -> None:
    """Mark the job queued and active before the thread exists, so a status read right after the 202 is truthful."""
    job = _jobs.Job(UPLOADS.dir_for(uid, aid))
    rec = job.read()
    rec.update(state="queued", error_code="")
    job.write(rec)
    with _jobs._ACTIVE_LOCK:
        _jobs.ACTIVE.add(aid)
    _threading.Thread(target=_job_worker, args=(uid, aid, rid), daemon=True, name=f"dg-job-{aid[:8]}").start()


def _job_json(st: dict, aid: str) -> dict:
    out = dict(st, assessment_id=aid, status_url=f"/jobs/{aid}")
    if st.get("state") == "completed":
        out["result_url"] = f"/doc-results/{aid}"
    return out


@app.post("/jobs")
async def jobs_create(request: Request):
    uid = _user_id(request)
    if uid is None:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    async with request.form() as form:
        vendor = str(form.get("vendor") or "Unnamed vendor")[:200]
        payloads = await read_uploads(form)
    if not payloads:
        return JSONResponse({"error": "no files were uploaded"}, status_code=400)
    aid = secrets.token_hex(16)
    assessment_id_var.set(aid)
    try:
        UPLOADS.save(uid, aid, payloads)
        job = _jobs.Job(UPLOADS.dir_for(uid, aid))
        job.create(aid, vendor, [s.name for s in _job_stages()])
    except (OSError, ValueError) as exc:
        log_event("job_create_failed", code=ErrorCode.STORAGE_FAILED, level=logging.ERROR, error_type=type(exc).__name__)
        return JSONResponse({"error": "could not store the upload", "error_code": ErrorCode.STORAGE_FAILED.value}, status_code=500)
    log_event("job_queued", file_count=len(payloads), bytes=sum(len(d) for _, d in payloads))
    _start_job(uid, aid, request_id_var.get())
    return JSONResponse(_job_json(job.status(), aid), status_code=202)


@app.get("/jobs/{job_id}")
def jobs_status(job_id: str, request: Request):
    uid = _user_id(request)
    if uid is None:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    got = _job_view(uid, job_id)
    if got is None:
        return JSONResponse({"error": "Unknown job"}, status_code=404)
    return JSONResponse(_job_json(got[1], job_id))


@app.post("/jobs/{job_id}/resume")
def jobs_resume(job_id: str, request: Request):
    uid = _user_id(request)
    if uid is None:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    got = _job_view(uid, job_id)
    if got is None:
        return JSONResponse({"error": "Unknown job"}, status_code=404)
    job, st = got
    if not job.resumable():
        return JSONResponse({"error": "job is not resumable", "error_code": ErrorCode.JOB_NOT_RESUMABLE.value,
                             "state": st["state"]}, status_code=409)
    assessment_id_var.set(job_id)
    log_event("job_resume", state=st["state"], completed_stages=st.get("completed_stages", []))
    _start_job(uid, job_id, request_id_var.get())
    return JSONResponse(_job_json(job.status(), job_id), status_code=202)


# ---------------------------------------------------------------------------
# CP025 public integration surface. These endpoints expose platform capability
# metadata only; evidence/assessment endpoints continue to use existing auth.
@app.get('/api/v1/status')
def api_v1_status():
    from driftguard_platform.ai import registry as ai_registry
    from driftguard_platform.frameworks import registry as fw_registry
    from driftguard_platform.config import PlatformConfig
    from driftguard_platform.persistence import registry as storage_registry
    from driftguard_platform.integrations import registry as connector_registry
    from driftguard_platform.secrets import registry as secret_registry
    return {
        'api_version':'v1',
        'service':'DriftGuard',
        'deterministic_authority':True,
        'ai_default':__import__('os').getenv('DRIFTGUARD_AI_PROVIDER','disabled'),
        'storage_provider':PlatformConfig.from_env().storage_provider,
        'storage_providers':list(storage_registry.names()),
        'secret_providers':list(secret_registry.names()),
        'connector_providers':sorted(connector_registry._factories),
        'frameworks':[{'key':f.key,'version':f.version} for f in fw_registry.list()],
        'capabilities':['evidence','assessments','findings','remediations','integrations','webhooks','byoai'],
    }

@app.post('/api/v1/evidence/mapping/confirm')
async def api_v1_confirm_mapping(request: Request):
    """Persist a human-confirmed column mapping so the same layout is read without AI next time."""
    import json as _json, os as _os
    from evidence.ai_mapping import MappingStore, confirm_workbook
    from evidence.tabular import read_tabular, TabularError
    authorize_api(request)
    path = _os.getenv('DRIFTGUARD_MAPPING_STORE')
    if not path:
        return JSONResponse({'error': 'DRIFTGUARD_MAPPING_STORE is not configured'}, status_code=409)
    async with request.form() as form:
        payloads = await read_uploads(form)
        role, raw = str(form.get('role') or ''), str(form.get('mapping') or '')
        customer = str(form.get('customer') or _os.getenv('DRIFTGUARD_CUSTOMER', 'default'))[:64]
    try:
        mapping = _json.loads(raw)
        workbook = read_tabular(*payloads[0])
    except (ValueError, IndexError, TabularError):
        return JSONResponse({'error': 'Need one readable file and a JSON object in mapping'}, status_code=400)
    if not isinstance(mapping, dict) or not confirm_workbook(MappingStore(path, customer), workbook, role, mapping):
        return JSONResponse({'confirmed': False, 'error': 'Mapping does not match the file or the role'}, status_code=422)
    return JSONResponse({'confirmed': True, 'role': role, 'customer': customer})

@app.get('/api/v1/ai/capabilities')
def api_v1_ai_capabilities():
    return {
        'provider_neutral': True,
        'operations':['classify_artifact','extract_facts','map_controls','detect_conflicts','explain'],
        'authoritative_compliance_verdicts': False,
        'default_mode':'disabled',
    }
