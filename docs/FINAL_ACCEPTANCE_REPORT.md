# DriftGuard CP015 Final Acceptance Report

Release decision: **RELEASE CANDIDATE — BLOCKERS REMAIN**.

## Exact acceptance results
- Automated repository suite: **478 passed**.
- Python compileall: **PASS**.
- Focused CP011/CP012/provider/CP013/CP015 acceptance group: **55 passed**.
- Original evidence pack: **52/52 ingested**, 26 structured artifact classifications, 29 questionnaire contracts, 17 claims; 0 Established, 8 Partial, 17 Not Established, 3 Clarification, 1 Conflict, 0 Not Evaluated.
- Semantic provider in offline acceptance: **SEMANTIC_UNAVAILABLE**; no semantic facts fabricated.
- Browser E2E: **BLOCKED** before application navigation by Chromium policy: `ERR_BLOCKED_BY_ADMINISTRATOR` at `http://127.0.0.1:8765/`. Failure screenshot is under `artifacts/cp014-screenshots/workflow-failure.png` when produced by the test.

## Release gate
The repository is not labelled DRIFTGUARD MVP FINAL because the mandatory real-browser test did not pass in this environment. Run `PYTHONPATH=backend/src pytest -q backend/tests/browser/cp014_browser_acceptance.py` on an environment where Chromium may access localhost.
