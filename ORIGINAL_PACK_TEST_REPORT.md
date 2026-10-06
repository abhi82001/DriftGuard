# Actual synthetic audit pack regression — 2026-09-30

Source: user-supplied `DriftGuard_SOC2_Synthetic_Audit_Evidence_Test_Pack(1).zip`.

## Actual observed output (offline batch runner)

- 52 evidence documents in 15 domains, plus `MANIFEST.csv` (53 total files).
- Ingestion: **52/52 successful** after adding JSON input with JSON-path provenance.
- Structured tabular QA: **26 files inspected**, **1 recognized USER_ACCESS_REVIEW** (Q3_Access_Review.xlsx, NEEDS_REVIEW, nine checks), **25 UNCLASSIFIED** (not validated, not passed).
- Deterministic questionnaire pass over all 52 extracted documents: **0 established, 3 partially established, 25 default missing-material, 1 clarification required; only 4 recognized claims**. Twenty-one of the 29 questions still lack implemented contracts. These are not full semantic outcomes.
- All 138 unit/regression tests passed with `-W error`; knowledge validator returned 0 errors and 0 warnings.

## Interpretation and blockers

This pack exposes that the present architecture is NOT a complete MVP. The structured QA supports only user access review. The local document analyzer recognizes six topics and eight question contracts, not all 29. Upload API limits one request to 10 files; the offline runner processes the whole pack for diagnostics. JSON was a genuine ingestion defect and has been corrected; this does NOT make JSON MFA configuration automatically sufficient evidence. No external semantic provider was invoked. A valid result must not treat unclassified files or unsupported questionnaire questions as control failures.

## Reproduce

From the extracted repository root:

```bash
python -m pip install -r backend/requirements.txt
python -m pytest -q backend/tests knowledge/soc2/tests -W error
python knowledge/soc2/validate.py
python run_original_pack.py test_evidence/driftguard_soc2_test_pack
```

Inspect `ORIGINAL_PACK_RUN_RESULTS.json` for file-by-file diagnostics. Run `run_original_pack.py` again to regenerate it. Do not present this build as final general-purpose semantic SOC 2 analysis until the remaining contracts and artifact validators are implemented and independently validated.
