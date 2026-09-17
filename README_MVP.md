# DriftGuard MVP

## What it demonstrates

**Document-first:** company name + upload security material → local extraction →
analysis against existing CC6/CC7 knowledge only → what is `ESTABLISHED`,
`PARTIALLY_ESTABLISHED`, `NOT_ESTABLISHED`, `CLARIFICATION_REQUIRED`, each with
source file and page/sheet/row → then only the unsettled questions under
*DriftGuard needs clarification*, evaluated through the existing CP002/CP003-CP005
path. Findings and remediations come only from the knowledge base.

**Manual assessment** (the original 29-question flow) is still available from the
homepage.

Supported uploads: `.pdf`, `.docx`, `.xlsx`, `.csv`, `.txt`, `.md` (max 10 files,
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

## Run against real Claude

```bash
$env:ANTHROPIC_API_KEY="<your key>"; $env:DRIFTGUARD_CLAUDE_MODEL="<model id>"; uvicorn backend.src.app:app --reload
```

`DRIFTGUARD_CLAUDE_MODEL` is required (no model id is assumed). If the key, model
or SDK is missing, semantic items degrade to `NEEDS_REVIEW` and the assessment
still completes. Never commit an API key.

## Browser

http://127.0.0.1:8000

## Tests

```bash
python backend/tests/run_tests.py
```

## Upload → analyze workflow

1. Enter the company name and select files, then **Analyze Documents**.
2. Results show established / partially established / clarification required /
   not evidenced, with source filename and page-sheet-row provenance.
3. Answer the follow-up questions DriftGuard still needs, or open the full
   questionnaire.

## Known limitations

- Document analysis is local deterministic keyword matching against existing
  evidence expectations — not model reasoning. Model-assisted document analysis
  can reuse the CP005 adapter later.
- Policy text can never be more than `PARTIALLY_ESTABLISHED`; missing material is
  reported as not evidenced, never as a control failure.
- In-memory state only: assessments are lost on restart. Uploaded bytes are read
  in memory and discarded; no file is stored. No database, no auth,
  no multi-tenancy.
- Only SEMCOND-0001 (QN-ACCESS-001-Q09) and SEMCOND-0002 (QN-OPS-001-Q03) have
  semantic conditions; other free-text answers report `NEEDS_REVIEW` with a
  reason instead of being guessed.
- No evidence upload, aggregation, export, or criterion-level scoring.
- Real-Claude mode has never been exercised against the live API here; all tests
  use fakes or demo mode.
- Single-process local demo only; no production hardening.
