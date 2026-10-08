# DriftGuard

Evidence-QA backend: turns uploaded evidence (XLSX/CSV) into facts, validates them, maps them to
questionnaire questions, and reports observations. It never issues compliance verdicts.

## Principle
- **Facts are the primary unit.** Everything downstream (checks, mapping, sufficiency, reports) is derived from facts.
- **Every fact needs provenance** (artifact + locator, e.g. sheet/cell ref). `validate_fact` rejects facts without subject, predicate, artifact_id or locator.
- **Unverifiable facts are rejected**, not guessed or repaired. Unrecognised input is "unread material", never a negative result about a control.
- No COMPLIANT/PASS/FAIL/CERTIFIED/AUDIT_OPINION anywhere (see `PROHIBITED` in `ai.py`, `PROHIBITED_VERDICTS` in `semantic.py`).
- Knowledge defines requirements; engine evaluates; AI may interpret text but never invents requirements.

## Working rules
1. Plan first and wait for the user's OK before editing code.
2. Keep the regression suite green; do not weaken or delete tests to make them pass.
3. Run only tests related to the change (single file or `-k`), not the whole suite, unless asked.
4. Do not read the whole repo; open only the files the task names or the file map points to.
5. Report failures honestly: show the failing output, say what was skipped or unverified.

## File map (backend/src)
- `evidence/pipeline.py` — joins stages: tabular -> classify -> extract -> validate -> `StructuredEvidenceResult`. Never raises on bad input; extraction never validates, validation never extracts.
- `evidence/classify.py` — structural-only classification (sheet names, headers, first-column labels); 4 signal groups, needs `review_campaign` + >=3 groups for USER_ACCESS_REVIEW, else UNCLASSIFIED.
- `evidence/schema_generalization.py` — header-synonym role inference for unfamiliar tables; returns None when ambiguous or LOW confidence.
- `evidence/mapping.py` — evidence -> questionnaire question/control lineage (QN-ACCESS-001; Q01, Q03-Q06 only, rest NOT_EVALUATED). Exact evidence-ID match only.
- `evidence/sufficiency.py` — 8 ordered dimensions per question; unknowns stay NOT_EVALUATED.
- `evidence/report.py` — presentation only; re-words existing checks, carries provenance untouched, no analysis.
- `evidence/authority.py` — document authority (attestation vs contract/privacy/marketing/subprocessor), product scope, report type, audit period; only attestations establish controls, third-party reports (Databricks, Nuance) cannot.
- `evidence/specificity.py` — generic-value rule (True/required/recorded need a topic anchor) and which attributes can truly conflict.
- `evidence/reproducibility.py` — `canonical_result`, `run_stamp` (input hash, assessment date, engine/grammar/knowledge versions).
- `driftguard_platform/facts.py` — `CanonicalFact`, `validate_fact`, `deduplicate_facts`.
- `driftguard_platform/ai.py` — provider-independent AI boundary (disabled by default, OpenAI adapter, `validate_result` requires source_ids for grounded ops).
- `evaluation/engine.py` — deterministic gap-signal grammar 1.0.0 (equals, in, not_includes_all); free text -> SEMANTIC_EVALUATION_REQUIRED; typed errors, no silent false.
- `evaluation/semantic.py` — grounded semantic request builder + `validate_semantic_result` for untrusted model output.

## Tests
Test file locations were not inspected when this file was written; confirm paths with `Glob backend/tests/**/test_*.py` before running.
Run one related file or keyword only:
```
python -m pytest backend/tests/<test_file>.py -q
python -m pytest backend/tests -k "<module_or_feature>" -q
```
Suggested pairing: evidence/* changes -> evidence tests; `facts.py`/`ai.py` -> platform tests; `engine.py`/`semantic.py` -> evaluation tests.

## Progress
CP019 (evidence authority and explainability) — done, uncommitted; tests: `backend/tests/test_cp019_*.py`
- [x] 1 Authority/scope/period/generic-value/conflict rules (`documents.py` `_area`/`_evaluate`, `evidence/authority.py`, `evidence/specificity.py`)
- [x] 2 Typed extraction statuses, dependency hints, SHA-256 de-dup, OCR behind `DRIFTGUARD_OCR=1` (`ingestion.py`; OCR itself unverified: no Tesseract here)
- [x] 3 Question explanations, grouped gap requests, customer labels (`evidence/report.py` `build_question_reports`)
- [x] 4 Reproducibility test, run stamp, AI marking (model facts cannot establish or conflict alone)
- Backlog (out of scope): AI gateway/OpenRouter/model switching, assessment delete/archive/rename/search UI, dashboards/UI polish, tenant isolation, retention, background jobs, multi-framework expansion.
- Open: `assessment.py` semantic path turns a model's omitted finding into STATUS_NO_GAP; bridge letters do not extend periods; authority rules are filename-based.

Original phase plan:
Phase order: 7, 3, 8, 2, 4, 5, 6.
- [ ] Phase 7 — TODO
- [ ] Phase 3 — TODO
- [ ] Phase 8 — TODO
- [ ] Phase 2 — TODO
- [ ] Phase 4 — TODO
- [ ] Phase 5 — TODO
- [ ] Phase 6 — TODO
