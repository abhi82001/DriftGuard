# CP017 Grounded Real Semantic Intelligence

CP017 hardens the existing CP012 evidence-fact semantic boundary rather than creating a second verdict engine.

## Architecture

Document segment -> real provider candidate facts -> schema/ontology/role/confidence/exact-quote/locator/qualification validation -> canonical NarrativeFact -> SecurityClaim -> deterministic CP009 questionnaire logic.

The provider cannot issue compliance verdicts. Deterministic extraction has priority for the same grounded source location and canonical attribute; disagreement is retained as a semantic conflict diagnostic. Provider failure degrades safely and deterministic analysis continues.

## Runtime hardening

- Real provider is reported active only when provider name, model, API key and Anthropic SDK are available.
- Credentials are environment-only and are never written to reports.
- Timeout, retry, output-token, segment-count and segment-size limits are bounded.
- Prompt-injection text remains untrusted document data.
- Exact supporting quote and exact source locator are mandatory.
- Planned/future/conditional affirmative operating claims are rejected.
- Prohibited compliance/audit verdict language is rejected.
- Semantic conflicts/rejections are exportable diagnostics.

## Live provider gate

The implementation contains `scripts/cp017_live_semantic_smoke.py`. In the build environment the Anthropic SDK/API credentials were not configured, so the real network smoke test correctly returned `NOT_RUN / SEMANTIC_UNAVAILABLE`. No fake provider was used to claim this gate passed.
