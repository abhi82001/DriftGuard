# CP017.1 Independent-Review Hardening

## Result
Implementation hardening PASS; live Anthropic provider gate PENDING because no API key/model is configured in the build environment.

## Independent review items closed
- Clean test dependencies: root `requirements-dev.txt` routes to backend dev requirements; `pytest` and `httpx` are explicit.
- Aggregate runner: `python backend/tests/run_tests.py` invokes the complete pytest collection and returns pytest's exit code.
- End-to-end scenario fixtures through `run_pack.py`: conflict, stale, missing, ambiguous/unclassified, and DR objective miss.
- General stale evidence: explicit evidence-quality state `STALE`; questionnaire semantics remain conservative (stale operating evidence becomes partial/conflict as applicable, never a control-failure verdict).
- Unclassified evidence: remains `MISSING` as an evidence state for backward compatibility but now always has `needs_review=true`.
- Upload edges: empty rejected, oversized rejected, non-UTF8 plain text safely decoded with replacement characters.
- Semantic provider failure: timeout/crash is isolated per segment and cannot become a silent pass.
- `run_pack.py` now exports questionnaire reasons/provenance, structured evidence states, graph observations and recovery observations and accepts an explicit assessment date.

## Verification
- Full suite: 543 passed, 0 failed.
- Original pack: 52 evidence files + MANIFEST.csv = 53 parsed, 0 rejected.
- Original questionnaire counts: 0 Established / 8 Partial / 17 Not Established / 3 Clarification / 1 Conflict / 0 Not Evaluated.
- Semantic status in offline acceptance: SEMANTIC_UNAVAILABLE.

## Intentional semantics
`OBJECTIVE_NOT_MET` remains a recovery observation with `NEEDS_REVIEW`; it is not automatically a SOC 2/control failure.
`STALE` is an evidence-quality state, not a questionnaire compliance verdict.

## Remaining gate
Run `scripts/cp017_live_semantic_smoke.py` with `ANTHROPIC_API_KEY` and `DRIFTGUARD_CLAUDE_MODEL` in a credentialed environment. A mock/stub cannot close this gate.
