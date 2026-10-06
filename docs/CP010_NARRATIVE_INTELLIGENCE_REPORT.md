# CP010 Narrative Intelligence Acceptance Report

## Decision

**CP010 PASS — grounded narrative foundation implemented.** This is not a claim that narrative coverage is complete for every future document. BCP/DR-specific intelligence remains CP011, and production semantic-provider orchestration remains a later checkpoint.

## Architecture added

- `narrative_intelligence.py`: canonical `NarrativeFact`, `FactProvenance`, ontology, claim types, qualifiers, content-first source-role classification, deterministic grounded extraction, and validation of untrusted semantic candidates.
- `narrative_claims.py`: compatibility adapter into CP009 `SecurityClaim` contracts plus a composite extractor preserving proven legacy rules.
- Ingestion segments now retain `heading` and `segment_type`; DOCX headings/paragraphs/tables and PDF pages keep source locators.
- Semantic providers are explicit. No provider is silently invoked in DEMO/local deterministic mode.

## Canonical fact fields

`fact_id, concept, attribute, value, normalized_value, claim_type, qualifiers, scope, subject, time_period, effective_date, source_role, artifact_type, confidence, extraction_method, provenance`.

Provenance includes filename, locator, exact supporting excerpt and page/paragraph/table fields where available.

## Safety / grounding

The extractor preserves negation, planned/future language, exceptions, conditional wording and historical language. Negative/planned/conditional facts are not promoted into affirmative CP009 evidence. Semantic candidates are rejected for unknown concepts, invalid roles/types, low confidence, missing locators, invented quotes, or prohibited compliance-verdict language. CSV/XLSX header rows are not promoted into operating facts.

## Tests

- Full repository: **425 passed**.
- Python compilation: **passed**.
- CP010 tests cover ontology breadth, content-first role classification, exact provenance, DOCX heading segmentation, negation, planned state, exceptions, conditional wording, header false-positive prevention, semantic quote/locator/concept/verdict rejection, and provider-candidate validation.
- Existing CP009/document tests remain passing.

## Original 52-file pack

- Documents parsed: **52/52**
- Structured tabular artifacts classified: **26**
- Documents producing new canonical deterministic narrative facts: **11**
- Canonical deterministic narrative facts: **19**
- Total questionnaire claims after legacy + grounded deduplication: **17** (CP009 baseline was 4)
- Questions receiving at least one eligible fact: **9/29**
- Semantic candidates rejected during this offline run: **0**, because no semantic provider was configured or called. Rejection behavior is covered by tests; DriftGuard does not pretend semantic analysis occurred.
- Questionnaire outcome: **0 Established, 8 Partial, 17 Not Established, 3 Clarification, 1 Conflict, 0 Not Evaluated**.

Canonical deterministic facts by questionnaire topic:

- boundary_baseline: 1
- data_egress: 1
- encryption_at_rest: 2
- endpoint_protection: 2
- incident_declaration: 2
- mfa: 2
- physical_access_review: 1
- physical_offboarding: 1
- postmortem: 1
- public_admin_exposure: 1
- security_configuration: 1
- temporary_boundary_rule: 2
- termination: 1
- vulnerability_management: 1

## Remaining limitations

1. Deterministic extraction is deliberately conservative; only 11/52 pack documents yield canonical narrative facts. This is preferable to manufacturing evidence from generic keywords.
2. The general semantic-provider boundary and grounding validator exist, but the offline acceptance run had no configured semantic provider. Provider orchestration/general model execution remains separate work.
3. BCP/DR/backup-specific fact extraction and reconciliation are intentionally left for CP011.
4. Cross-artifact graph/reconciliation remains CP013.
5. Browser E2E acceptance remains CP014.

The checkpoint passes because CP010 establishes the grounded fact/segmentation/ontology/qualification/source-role/semantic-validation architecture and integrates it safely with CP009 without false semantic claims. It does **not** label DriftGuard production-ready.
