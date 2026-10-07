# DriftGuard AI and Enterprise Architecture (CP018–CP029)

DriftGuard keeps deterministic compliance evaluation authoritative. AI is an evidence-understanding and explanation layer, never an audit-opinion generator.

## AI boundary

`driftguard_platform.ai.AIProvider` is the provider-neutral contract. The first live adapter is OpenAI and is lazy-loaded. `DRIFTGUARD_AI_PROVIDER=disabled` is the safe default; `openai` can be selected when the optional SDK and server-side `OPENAI_API_KEY` are configured. Provider results are normalized into DriftGuard-owned `AIResult` objects and validated for confidence, grounding, and prohibited compliance verdicts.

Canonical AI-derived facts require artifact and locator provenance. High-confidence deterministic classifications remain authoritative; AI is a fallback for unknown/ambiguous artifacts.

## Evidence intelligence

Canonical facts use subject/predicate/value plus provenance and temporal/scope fields. Existing deterministic evidence graph logic remains intact and privacy schemas extend structural recognition without filename-specific rules. Policy-effectiveness comparison distinguishes design evidence, operating evidence, exceptions, conflicts, and insufficient evidence.

## Frameworks and privacy

A versioned framework registry provides extension points for SOC 2, ISO 27001 and DPDP. Privacy evidence types cover consent, rights/breach logs, and processor assessments. Framework knowledge remains authoritative; AI can propose mappings but cannot make them authoritative.

## Enterprise integrations

The connector contract normalizes external records before they enter compliance logic. Credentials are intentionally outside connector records. The enterprise security helpers provide tenant/scope authorization, idempotency keys, signed webhooks and replay windows.

## BYOAI

`TenantAIConfig` separates tenant AI policy from provider implementation. AI may be disabled per tenant and capabilities can be constrained. Secrets are passed to provider construction rather than persisted in the config model.

## Grounded assistant and auditor trace

The assistant refuses to answer without sources and explains existing assessments rather than changing them. `AuditTrace` models framework -> control -> requirement -> evidence -> facts -> evaluation -> finding/remediation lineage.

## Production boundary

Upload inspection provides content hashing, archive member/expansion limits and path-traversal checks. Existing DriftGuard upload security, authentication, bounded stores and privacy-safe telemetry remain authoritative and should be used alongside these helpers.

## Current API discovery

`GET /api/v1/status` and `GET /api/v1/ai/capabilities` expose stable capability metadata. Existing evidence/assessment routes remain backward compatible. Public resource mutation APIs should only be expanded when persistent tenant storage and production credential management are available; this implementation deliberately does not pretend in-memory state is enterprise persistence.
