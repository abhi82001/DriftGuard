# CP013 — Q3 access review golden regression

The exact bundled `backend/tests/fixtures/files/Q3_Access_Review.xlsx` is a fixed regression input, exercised by `backend/tests/test_cp013_q3_golden.py`.

- Reviewed population: 5; recognized retain 1, revoke 2, investigate 1; row 6 `excluded` remains unrecognized and requires an approved exclusion policy and provenance before classification.
- Revoke/modify population: 2; completed: 1; derived unresolved remainder: 1. All-row status column: 2 Open, including investigate row 5. These metrics describe different populations, must not be summed or called a contradiction.
- Remediation-applicable rows: 3 (rows 3, 4, 5); affirmative confirmations 0; timestamp requiring validation 1, unavailable 1, missing 1. Excluded row 6 is not included simply because its confirmation column has a note.
- Timestamp `2026-10-07 08:52 utc` in row 3 column H is not affirmative confirmation. `evidence.temporal_review.review_recorded_confirmation_dates` flags it when, and only when, an authoritative assessment cutoff is explicitly supplied earlier than October 7. This is an opt-in review helper, not an automatically assumed clock-based check; integrating an approved assessment date into the UI is a separate task.

Run: `python -m pytest -q backend/tests/test_cp013_q3_golden.py` and full regression `python -m pytest -q backend/tests knowledge/soc2/tests -W error`.
