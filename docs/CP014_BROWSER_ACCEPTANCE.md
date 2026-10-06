# CP014 Browser Acceptance

## Status: CHECKPOINT FAIL — environment browser-navigation blocker

CP014 product/UI implementation is complete enough for ASGI-level acceptance, but the mandatory real Chromium workflow cannot be truthfully marked PASS in the current execution environment. Playwright launches `/usr/bin/chromium` and Uvicorn is reachable from Python, but Chromium rejects `http://127.0.0.1:8765/`, `http://localhost:8765/`, and `http://0.0.0.0:8765/` with `net::ERR_BLOCKED_BY_ADMINISTRATOR` before a browser request reaches DriftGuard.

The executable browser acceptance is retained at `backend/tests/browser/cp014_browser_acceptance.py`. It captures `artifacts/cp014-screenshots/workflow-failure.png` on a workflow failure. Run it in a normal Windows/Linux browser environment with:

`PYTHONPATH=backend/src pytest -q backend/tests/browser/cp014_browser_acceptance.py`

## Implemented UX

- Upload form exposes an aria-live ingestion/analyzing state.
- Dashboard separates files received, files parsed, structured artifacts validated, narrative documents analyzed, questions evaluated/not evaluated, Established, Partial, Not established, Clarification, Conflict, and runtime NOT_EVALUATED.
- Semantic state is explicit. DEMO shows `DETERMINISTIC ONLY`; absent provider shows `SEMANTIC ANALYSIS UNAVAILABLE`; deterministic extraction is never presented as semantic analysis.
- Question rows expose Why, known evidence, unknown facts, evidence needed, contradiction state, rejected-evidence policy, filename, locator, artifact/source role, extraction method and supporting excerpt.
- Evidence QA exposes recognized artifact type, validator, checks performed, checks not performed/limitations, fact count, exceptions and provenance. Classification is explicitly not represented as validation success.
- Cross-artifact and BCP/DR surfaces from CP011/CP013 remain integrated.
- JSON report export added at `/export/{assessment_id}` with 29 question results and provenance.
- Clarification submission remains available and redirects to reassessment results.

## Automated acceptance

- Complete repository suite: **467 passed**.
- CP014 ASGI/UI acceptance: **7 passed**.
- Python compilation: **PASS**.
- Original synthetic pack: **52/52 ingested**, 26 structured types classified, 29/29 contracts, 0 runtime NOT_EVALUATED.
- Original-pack questionnaire result: 0 Established, 8 Partial, 17 Not established, 3 Clarification, 1 Conflict.
- Claims: 17 deterministic/grounded claims. No semantic facts were fabricated.

Negative acceptance covers unsupported extension, malformed PDF, oversized upload, mixed narrative+tabular evidence, and unavailable semantic provider. Existing CP009-CP013 suites retain contradiction, grounding, malformed semantic output, and cross-artifact safety coverage.

## Browser workflow intended by the retained Playwright test

1. Start real Uvicorn server.
2. Open DriftGuard in Chromium.
3. Enter vendor and upload mixed evidence.
4. Wait for document results.
5. Verify semantic status and separated dashboard metrics.
6. Inspect evidence trace/provenance.
7. Open Evidence QA and verify validator scope.
8. Return to assessment.
9. Submit a clarification when present and confirm reassessment results.
10. Create another document assessment and download the JSON report.

## Remaining blocker

Run the retained Playwright test on the target Windows/Git Bash environment or another host where Chromium is allowed to reach localhost. Until that passes, CP014 is **not** labelled FINAL/PASS under the user's mandatory acceptance rule.
