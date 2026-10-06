# CP012 Semantic Acceptance Report

## Status: PASS (provider integration implemented; live provider not configured in acceptance environment)

CP012 adds a provider-independent grounded semantic evidence extraction path. The LLM is restricted to proposing candidate evidence facts from one DriftGuard-selected source segment. It never chooses a questionnaire status or SOC 2 conclusion.

## Architecture

`Document -> parser/segments -> SemanticSegmentRequest -> provider -> SemanticCandidate -> schema/ontology/role/confidence validation -> exact quote+locator grounding -> qualifier/entailment guard -> NarrativeFact -> SecurityClaim -> existing CP009 deterministic questionnaire evaluator`.

The CP010 deterministic extractor remains active and is not replaced. When no provider is configured, semantic status is `SEMANTIC_UNAVAILABLE`; DriftGuard does not simulate semantic analysis.

## Provider

`SemanticEvidenceProvider` is provider-independent. `ClaudeEvidenceProvider` is an Anthropic adapter using structured JSON-schema output. It is configured only when `DRIFTGUARD_SEMANTIC_PROVIDER=claude` and `DRIFTGUARD_CLAUDE_MODEL` is set; credentials remain SDK/environment concerns.

## Safety / grounding gates

Candidates are rejected for unknown concepts, unapproved attributes, invalid claim/source roles, role mismatch, confidence below 0.70, wrong locator, quote not present verbatim in the source segment, prohibited compliance/pass/fail/certification language, affirmative values contradicted by negation, or future/conditional language presented as current operation.

Evidence text is labelled `untrusted_document_text`; prompt-injection text is never executed. Provider errors/timeouts fail closed per segment.

## Tests

- CP011 baseline before CP012: 438 passing.
- CP012 semantic tests added: 14.
- Full suite after CP012: **452 passed**.
- Python compilation: PASS.

Adversarial coverage includes hallucinated quote, wrong locator, filename controlled by DriftGuard, unknown concept/attribute, low confidence, source-role mismatch, negation, future plan, conditional statement, historical statement, exception, prompt injection, prohibited verdict language, timeout, unavailable provider, malformed provider output, contradictory grounded facts, structured Claude payload, hybrid integration, and no-provider behavior.

## Original 52-file pack

The original synthetic pack was freshly extracted and rerun after CP012:

- files ingested: **52/52**
- structured/tabular classifications: **26**
- questionnaire contracts: **29/29**
- established: **0**
- partially established: **8**
- not established: **17**
- clarification required: **3**
- conflict: **1**
- runtime NOT_EVALUATED: **0**
- questionnaire claims in deterministic/no-provider run: **17**
- semantic provider in acceptance environment: **SEMANTIC_UNAVAILABLE**
- semantic facts accepted from original pack in this run: **0** (no provider was configured; none were fabricated)

For every semantic fact produced in configured-provider operation, acceptance requires the chain `fact -> exact excerpt -> exact locator -> DriftGuard-owned source filename`. This invariant is enforced by `validate_candidate` and tested independently.

## Remaining limitations

1. No live Anthropic credential/model was available in this execution environment, so no external provider call was made against the 52-file pack. The adapter is tested at its network boundary with a fake client.
2. CP012 does not create broad cross-artifact entity reconciliation; that remains CP013.
3. Semantic extraction is segment-scoped and intentionally conservative; cross-segment inference must be implemented as explicit reconciliation, not model assumption.
4. In-memory web assessment storage/authentication are production-hardening concerns outside this checkpoint.

## Acceptance decision

**PASS for CP012 implementation.** Provider-independent extraction, structured provider adapter, grounding, provenance, fail-closed behavior, deterministic questionnaire integration, adversarial defenses, and explicit provider-unavailable behavior are implemented and tested. This is not a claim that a live external model was exercised in this environment.
