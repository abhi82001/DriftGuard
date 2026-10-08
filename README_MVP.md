# DriftGuard MVP

## What it demonstrates

**Document-first:** company name + upload security material → local extraction →
analysis against the repository's current SOC 2 knowledge and evidence contracts → what is `ESTABLISHED`,
`PARTIALLY_ESTABLISHED`, `NOT_ESTABLISHED`, `CLARIFICATION_REQUIRED`, each with
source file and page/sheet/row → then only the unsettled questions under
*DriftGuard needs clarification*, evaluated through the existing CP002/CP003-CP005
path. Findings and remediations come only from the knowledge base.

**Manual assessment** (the original 29-question flow) is still available from the
homepage.

Supported uploads: `.pdf`, `.docx`, `.xlsx`, `.csv`, `.txt`, `.md` (max 25 files,
5 MB each). No OCR, no images, no embeddings, no vector store. Uploaded content is
treated as untrusted data: instructions inside a document are never followed.

## Install

```bash
pip install -r backend/requirements.txt
```

## Run in demo mode (no API key, no network, no tokens spent)

```bash
DRIFTGUARD_DEMO_MODE=1 uvicorn backend.src.app:app --reload
```

PowerShell:

```bash
$env:DRIFTGUARD_DEMO_MODE=1; uvicorn backend.src.app:app --reload
```

Semantic results are then produced by a local deterministic stub and labelled
`DEMO` — they are not model output.

## Run against a real model

One configuration drives all AI use (semantic evaluation, grounded fact extraction, mapping assistance):

```bash
$env:DRIFTGUARD_AI_PROVIDER="anthropic"; $env:DRIFTGUARD_AI_MODEL="<model id>"; $env:ANTHROPIC_API_KEY="<your key>"; uvicorn backend.src.app:app --reload
```

Providers: `anthropic` (`ANTHROPIC_API_KEY`), `openai` (`OPENAI_API_KEY`), `openrouter` (`OPENROUTER_API_KEY`).
The model must be listed in `backend/src/driftguard_platform/ai_models.json` (or a file named by
`DRIFTGUARD_AI_CAPABILITIES_FILE`). If the provider, model, key or SDK is missing, semantic items degrade to
`NEEDS_REVIEW` and the assessment still completes; `/health` names what is missing. Never commit an API key.

`DRIFTGUARD_SEMANTIC_PROVIDER=claude`, `DRIFTGUARD_CLAUDE_MODEL`, `DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS` and
`DRIFTGUARD_SEMANTIC_MAX_RETRIES` still work as **deprecated** fallbacks for one release (the new variables win).

## Browser

http://127.0.0.1:8000

## Tests

```bash
python backend/tests/run_tests.py
```

Current consolidated baseline: **559 passed, 0 failed**. See `docs/CURRENT_BASELINE.md` for the current pack/API smoke results and interpretation of historical checkpoint reports.

## Upload → analyze workflow

1. Enter the company name and select files, then **Analyze Documents**.
2. Results show established / partially established / clarification required /
   not evidenced, with source filename and page-sheet-row provenance.
3. Answer the follow-up questions DriftGuard still needs, or open the full
   questionnaire.

## Known limitations

- Deterministic parsing/evaluation remains the authoritative path. Semantic-provider
  infrastructure exists, but broad provider-neutral AI evidence intelligence is not
  yet the primary document-understanding path.
- Statuses: question results are `ESTABLISHED`, `PARTIALLY_ESTABLISHED`,
  `NOT_ESTABLISHED`, `CLARIFICATION_REQUIRED`. `CONFLICT` (eligible sources
  disagree) and `NOT_EVALUATED` (no executable contract) are additional
  result states, reported in their own sections and counts. Without a semantic
  provider/API key the semantic layer reports `NEEDS_REVIEW`.
- Policy text can never be more than `PARTIALLY_ESTABLISHED`; missing material is
  reported as not evidenced, never as a control failure.
- Assessment/evidence processing remains oriented to local development rather than
  production multi-tenancy. Local account/session support exists, but enterprise
  persistence, tenant isolation, authorization and lifecycle controls remain future
  production-hardening work.
- Live semantic-provider behavior is an explicit acceptance gate; normal regression
  tests use controlled/fake or demo paths and do not require paid external calls.
- Single-process local demo only; no production hardening.

### Development / acceptance dependencies

Install the complete test environment before running acceptance:

```bash
pip install -r requirements-dev.txt
python backend/tests/run_tests.py
```

The development requirements include `pytest` and `httpx`; the aggregate runner invokes the complete pytest suite and returns pytest's exit code.

## CP018–CP029 extensibility layer

The current development tree adds a provider-neutral AI gateway, grounded canonical facts, policy-vs-operation evaluation, privacy schemas, a versioned framework registry, enterprise connector/webhook/BYOAI boundaries, grounded assistant/auditor lineage models and additional production upload controls. Deterministic compliance evaluation remains authoritative and AI is disabled by default. See `docs/AI_AND_ENTERPRISE_ARCHITECTURE.md` and `docs/CP018_CP029_IMPLEMENTATION_REPORT.md`.

## Security-hardened local run (2026-10-07)
Authentication is required by default for analysis workflows. Register/login in the UI before uploading evidence. For local HTTP, secure-cookie mode is off unless explicitly enabled. Production deployments should set `DRIFTGUARD_ENV=production`, which enables Secure session cookies. `DRIFTGUARD_REQUIRE_AUTH=0` exists only for explicit local/demo compatibility and must not be used for hosted deployments.
