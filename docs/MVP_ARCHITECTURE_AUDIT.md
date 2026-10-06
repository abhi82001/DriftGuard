# MVP architecture audit — 2026-09-30

The baseline repository is a real FastAPI application, not a complete general-purpose semantic evaluator. `backend/src/documents.py` has eight executable QUESTION_SPECS for 29 questionnaire questions; `backend/src/claims.py` is a narrow local deterministic extractor. `backend/src/evidence/pipeline.py` previously dispatched only USER_ACCESS_REVIEW to a structured validator. JSON ingestion was added in the prior interim checkpoint. The tabular and document pipelines produce separate results; a structurally valid risk register does not prove an access review was completed.

## Verified changes in this checkpoint

Added `backend/src/evidence/structured_registry.py`: 25 structurally identified register schemas (plus the existing user access review path) with explicit header combinations, row counts, identifiers, duplicate detection, critical field checks, and date parsing/future-date checks. These are **structural quality validators only**, not 25 independently designed domain sufficiency validators. Classification does not rely on the filename. An unrecognized header signature remains UNCLASSIFIED. Dates retain their source field meaning. No generic register facts are promoted to questionnaire operating evidence.

## Open critical architecture work

- Twenty-one questionnaire contracts remain without executable rules; the existing eight are limited.
- Grounded model-backed semantic extraction and schema-validation of provider responses are not connected to the complete document assessment route.
- Domain-specific content validations (risk scoring, deletion closure, rule exposure, asset-to-EDR matching, etc.) and cross-artifact reconciliation are not implemented by this generic schema layer.
- Structured QA results are displayed separately; they are not yet safely mapped to the 29 questionnaire sufficiency decisions.
- Full browser-based UI testing and clean Windows installation acceptance are still outstanding.

**Release status: INTERIM.** Never equate recognized structure or a zero issue count with control effectiveness.
