# Local synthetic test guide (not a production deployment guide)

1. Use an isolated development machine, supported Python environment and a virtual environment.
2. Install dependencies from the project's verified dependency inventory (pin versions before deployment); existing test environment requires FastAPI, python-multipart, openpyxl, python-docx, pypdf, jsonschema, referencing, httpx and pytest.
3. Run `python -m pytest -q backend/tests knowledge/soc2/tests -W error` and `python knowledge/soc2/validate.py`.
4. Optionally set `DRIFTGUARD_DEMO_MODE=1` and `DRIFTGUARD_API_KEY` to a locally generated secret. The key protects only `/api/evidence-map`.
5. Bind uvicorn to loopback only: `python -m uvicorn backend.src.app:app --host 127.0.0.1 --port 8000`. Do not enable public network exposure or use confidential uploads.
6. For the API send `x-driftguard-api-key` if configured. Limit uploads to 10 files and 5 MiB/file. Use the bundled anonymized/synthetic fixtures.

Production prerequisites: approved gateway SSO and RBAC covering **all** endpoints, tenant isolation and encrypted persistence, reverse-proxy request-body cap before multipart parsing, malware scanning and parser sandboxing, dependency audit, secret rotation, logs/monitoring, backup/restore, retention/deletion, operational runbook, performance and penetration tests, and written data owner approval.
