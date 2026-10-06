# CP017 Acceptance Report

**Result: IMPLEMENTATION COMPLETE; LIVE PROVIDER GATE PENDING.**

## Tests

- Measured CP017 baseline from packaged CP016 tree: 522 passed.
- Final complete repository suite: **535 passed, 0 failed**.
- CP017 + semantic focused tests: passed.
- Repository-root `python -m pytest -q` now works via `pytest.ini`.

## Regression

Original pack directory contains 52 evidence files plus `MANIFEST.csv` (53 supplied files). All 53 parsed with 0 rejected. Questionnaire counts remain:

- Established: 0
- Partial: 8
- Not Established: 17
- Clarification: 3
- Conflict: 1
- Not Evaluated: 0

Semantic status without real credentials: `SEMANTIC_UNAVAILABLE`.

## Verified CP017 behavior

- No API key/model/SDK => never reports semantic active.
- Provider failure => deterministic results survive; semantic status fails closed.
- Exact quote + locator grounding required.
- Prompt injection and prohibited verdict language rejected.
- Planned/future affirmative operation rejected.
- Deterministic fact wins same-location/attribute disagreement; conflict is surfaced.
- New non-conflicting grounded semantic facts may augment deterministic extraction.
- Segment/token/timeout/retry configuration is bounded.
- Export includes semantic rejection/conflict diagnostics.

## Mandatory live gate not run

The build environment has no Anthropic SDK/API credential configured. `scripts/cp017_live_semantic_smoke.py` returned `NOT_RUN / SEMANTIC_UNAVAILABLE`. Therefore CP017 must not be labelled fully acceptance-PASS until one real provider call is executed successfully in a credentialed environment and the returned fact passes DriftGuard grounding validation.

CP018 readiness: **NOT READY for final release gate until the CP017 live-provider smoke passes.**
