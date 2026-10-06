# CP014 files changed

- `backend/src/app.py` — dashboard metrics, ingestion status, semantic-state wording, question trace detail, Evidence QA validator scope, JSON export.
- `backend/src/documents.py` — records original file-received count separately from parsed documents.
- `backend/tests/test_cp014_ui_acceptance.py` — UI/API and negative acceptance.
- `backend/tests/browser/cp014_browser_acceptance.py` — real Uvicorn + Chromium Playwright workflow.
- `backend/requirements-dev.txt` — browser/test development dependencies.
- `docs/CP014_BROWSER_ACCEPTANCE.md` — acceptance evidence and blocker.
