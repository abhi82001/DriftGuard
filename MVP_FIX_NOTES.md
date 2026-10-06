# MVP safety correction — September 30, 2026

This build addresses an observed false positive in assessment 8c807a60ce80.

- Risk_Register.csv review date is not a completed access-review date.
- A risk-treatment mention of quarterly review cannot establish a documented policy cadence or operating campaign.
- Identity-population operating evidence requires an explicit completed access review and population evidence, not a date.
- Incidental dates and status words in unrelated tabular documents no longer automatically turn them into operating evidence.
- Assessment summary separately counts unclassified/unvalidated tabular uploads; zero QA exceptions is not represented as passing QA.
- Three adversarial regression tests were added.

## Known limitations (do not hide in the demo)

The structured Evidence QA pipeline currently validates USER_ACCESS_REVIEW only. Risk registers, data inventories and deletion records are intentionally UNCLASSIFIED, not failed and not validated. Document claims use a narrow local deterministic extractor even when the page says LOCAL; switching DEMO off does not enable model-based document intelligence. The 29-question set is wider than the extractor's coverage. No production-grade SOC 2 compliance conclusion is generated. Do not present this build as general-purpose evidence understanding.

For the MVP demonstration, show Q3_Access_Review.xlsx with its supported structured QA and show a policy as documented-design evidence. Explicitly label risk register and inventory/deletion CSVs as unsupported pending type-specific extraction/validation. Future work: dedicated artifact contracts and cross-artifact sufficiency, plus a separately tested model provider for document claims.

Run: `python -m pytest -q backend/tests knowledge/soc2/tests -W error`; `python knowledge/soc2/validate.py`; `python -m compileall -q backend/src`.
