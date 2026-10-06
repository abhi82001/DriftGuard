# DriftGuard CP009–CP014 execution checkpoint — INTERIM

This checkpoint is not a completed implementation of the full master prompt. The Phase 1 repository was copied before modification.

## Verified execution

- Baseline command: `PYTHONPATH=backend/src pytest -q backend/tests` → **140 passed** (not the previously reported 142 under this exact invocation).
- Added domain-specific row checks for data deletion closure and chronological order, risk-score ordering/treatment presence, firewall allow-rule expiry review, and vulnerability closure date/timeliness. These are **review flags**, not compliance verdicts.
- Added five focused regression tests including a misleading access-review filename for a risk-register schema.
- Current command: `PYTHONPATH=backend/src pytest -q backend/tests` → **145 passed**.
- Original pack command: `python run_original_pack.py /mnt/data/full_mvp_review/driftguard_soc2_test_pack` → **52/52 ingested; 26 tabular classified; 0 established, 3 partial, 25 missing, 1 clarification; four extracted claims**. The path is the test runner's local path, not an included release dependency.
- See `ORIGINAL_PACK_RUN_RESULTS.json` and `docs/QUESTIONNAIRE_ACCEPTANCE_MATRIX.md`.

## Not completed

- 21 questionnaire contracts still lack executable semantics; the 29-row matrix explicitly labels this.
- Only four register types gained additional domain rules in this checkpoint; the remaining schema recognizers are mostly structural.
- No general model-backed grounded semantic extraction, no comprehensive cross-artifact reconciliation, and no independently adjudicated 29-question expected-result oracle.
- Browser UI smoke testing and clean Windows installation were not performed.

**Release status: INTERIM.** Missing evidence is not a control failure. The original pack's 0 established results are not a measure of vendor compliance.
