# Platform Architecture Hardening — 2026-10-07

## Scope

Incremental infrastructure decoupling and repository cleanup. The deterministic compliance engine was not rewritten.

## Implemented

- Central `PlatformConfig` for storage, secrets, and AI provider selection.
- `StorageProvider` + registry; built-in SQLite adapter.
- `AccountRepository` boundary for users, sessions, and saved-assessment history.
- SQLite-specific SQL moved out of `app.py` into `SQLiteAccountRepository`.
- `SecretProvider` + registry; environment-reference adapter.
- `ConnectorConfig` with non-secret settings and secret references.
- `AIProviderConfig` with secret-reference construction while preserving existing AI contracts.
- `/api/v1/status` exposes configured/available infrastructure provider names without secrets.
- `.env.example` contains safe configuration examples only.
- Contract tests prove future provider registration can occur without changing domain/compliance code.
- Removed generated caches, local Claude config, duplicate embedded pack ZIP, and an unreferenced sample file.
- Preserved historical acceptance artifacts referenced by release documentation.

## Verification

- Complete regression suite: 595 passed, 0 failed.
- External pack: 58 supplied, 58 processed, 0 rejected, 0 errors.
- Questionnaire distribution unchanged: 0 established, 10 partially established, 13 missing evidence, 5 clarification required, 1 conflict, 0 not evaluated.
- API smoke: `/`, `/login`, `/register`, `/api/v1/status`, `/api/v1/ai/capabilities`, `/openapi.json` all returned 200.

## Extension contract

Existing providers require configuration/secret references only. A genuinely new technology still requires one adapter because PostgreSQL/Firebase/identity/SIEM APIs have different semantics. That adapter must implement the relevant DriftGuard contract and register itself; the compliance engine and application routes must not be changed.

## Deliberate limitation

This checkpoint does not pretend PostgreSQL or Firebase support exists before those adapters are implemented and tested. It creates the stable boundary that makes adding them localized and contract-testable.
