# DriftGuard Security Hardening — 2026-10-07

This release addresses the independent web-layer audit findings without changing deterministic compliance authority.

## Implemented
- Production authentication boundary is enabled by default (`DRIFTGUARD_REQUIRE_AUTH=1` semantics; set `0` only for explicit local/demo compatibility).
- Assessment ownership is bound to the authenticated user and enforced on results, JSON export, PDF export, evidence report, and clarification flows.
- Assessment IDs now use the full 128-bit UUID hex value.
- Saved assessment persistence no longer uses pickle. It uses JSON with an explicit dataclass/module allowlist and rejects unknown saved-state types.
- Sessions expire after 8 hours and prior sessions are rotated/revoked on login.
- Passwords use PBKDF2-SHA256 with 600,000 iterations. Legacy 200,000-iteration hashes remain login-compatible and are upgraded after successful login.
- SameSite=Strict, HttpOnly session cookies. Secure cookies are automatically enabled when `DRIFTGUARD_ENV=production`, or explicitly with `DRIFTGUARD_SECURE_COOKIES=1`.
- Cross-origin unsafe requests are rejected when Origin is present.
- CSP, frame denial, nosniff, referrer, and permissions headers are emitted.
- Login and authenticated workload rate limits added.
- Request Content-Length is rejected before form parsing when above the bounded upload envelope.
- Saved-assessment quota is bounded to 100 per user with oldest-record eviction.
- API-key authentication remains available for `/api/evidence-map` when `DRIFTGUARD_API_KEY` is configured.

## Verification
- Complete suite: 587 passed.
- New security regression tests: 5 passed (included in 587).
- External acceptance pack: 58 supplied, 58 processed, 0 rejected, 0 errors.
- Questionnaire distribution: established 0, partially established 10, missing evidence 13, clarification required 5, conflict 1, not evaluated 0.

## Important boundary
This hardening release fixes the reported web-layer findings. It does not claim that the broader production blockers previously identified (durable multi-tenant production database architecture, external KMS/Vault, full production connector workers, complete auditor workspace, certified cloud deployment, and live AI-provider certification) are complete.
