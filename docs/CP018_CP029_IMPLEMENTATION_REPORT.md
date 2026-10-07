# CP018–CP029 implementation report

## Implemented in this development pass

- **CP018 AI gateway:** provider-neutral `AIProvider`, registry, disabled provider, lazy OpenAI adapter, normalized requests/results, confidence/grounding/verdict validation, correlation/usage metadata.
- **CP019 grounded AI evidence intelligence:** deterministic-first classification fallback, provenance-required AI fact extraction, canonical facts and deduplication.
- **CP020 evidence graph:** existing provenance-aware graph retained and extended with privacy/vendor relationship vocabulary; canonical facts provide a stable graph input boundary.
- **CP021 policy vs operating effectiveness:** typed requirements and deterministic threshold/SLA comparison with explicit insufficient/conflict/exception states.
- **CP022 privacy/DPDP:** structural consent, rights/breach and processor-assessment schemas; reusable privacy observations. The latest test pack's three privacy CSVs are now correctly classified without filename rules.
- **CP023 multi-framework:** versioned framework registry for SOC 2, ISO 27001 and DPDP plus authoritative mapping model.
- **CP024 integration gateway:** provider-neutral connector contract/registry and an Okta reference connector with injected HTTP client support, pagination cursor extraction and canonical identity records.
- **CP025 enterprise API/webhooks:** `/api/v1/status` and `/api/v1/ai/capabilities`; tenant/scope authorization primitives, deterministic idempotency keys, HMAC webhook signing and replay-window validation. Existing authenticated evidence API remains backward compatible.
- **CP026 BYOAI:** tenant AI configuration/policy boundary and provider selection through the CP018 registry.
- **CP027 grounded assistant:** source-required explanation path that receives existing assessment/facts and cannot operate without evidence sources.
- **CP028 auditor trace:** framework/control/requirement/evidence/fact/evaluation/finding/remediation lineage model.
- **CP029 production boundary:** SHA-256 evidence hashing, upload/archive size limits and archive path-traversal protection, complementing existing upload security/auth/bounded-state/telemetry hardening.

## Deliberately not misrepresented as complete production infrastructure

The codebase remains a local/MVP architecture in several areas. Production enterprise deployment still requires durable multi-tenant persistence, a real secrets manager/KMS, production identity provider/RBAC, distributed rate limiting/background jobs, connector credential vaulting, webhook delivery persistence/retry workers, and production observability/deployment infrastructure. The new contracts are designed so those facilities can be attached without changing compliance-domain logic.

Only OpenAI has a live new AI adapter in this pass; Anthropic already exists through the older semantic evaluator, but it has not been rewritten as a new `AIProvider` adapter. Azure OpenAI, Gemini and custom enterprise endpoints are extension points, not falsely advertised as implemented live providers.

The auditor workspace data lineage model is implemented; a full new frontend workspace was not fabricated in this pass because the existing UI architecture should consume stable API/data contracts rather than duplicate compliance logic.

## Security/threat model notes

Threats explicitly addressed by tests/contracts include AI compliance-verdict injection, ungrounded AI output, missing provenance, prompt-like evidence being treated as data by provider instructions, cross-tenant authorization primitives, webhook tampering/replay, insecure Okta endpoints, secret leakage from normalized connector records, archive path traversal, zip expansion/member limits, and deterministic fallback when AI is disabled.

Remaining deployment threats requiring infrastructure controls include credential theft at rest, database tenant-policy enforcement, SSRF egress policy for configurable enterprise endpoints, distributed denial-of-service/rate limiting, worker isolation, backup/recovery of persistent state, and organization-specific retention/deletion policy enforcement.
