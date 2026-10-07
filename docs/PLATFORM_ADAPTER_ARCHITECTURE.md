# DriftGuard Platform Adapter Architecture

## Rule

DriftGuard domain/compliance code must not depend on a database vendor, secret store, AI vendor, or enterprise connector. Infrastructure enters through a small contract and registry. Evidence is normalized before deterministic compliance evaluation.

## Storage

`driftguard_platform.persistence.StorageProvider` is the storage boundary. `sqlite` is the built-in adapter and remains the default. Selection is configuration-only:

```text
DRIFTGUARD_STORAGE_PROVIDER=sqlite
DRIFTGUARD_DATABASE_URL=sqlite:///backend/driftguard.db
```

A future PostgreSQL/Firebase/etc. implementation registers a provider against this contract. Adding a new technology may require an adapter because databases have different query/transaction semantics, but it must not require changes to the compliance engine.

The web application uses `AccountRepository` for users, sessions, and saved-assessment history. SQLite SQL is contained in `SQLiteAccountRepository`; `app.py` has no SQLite queries or SQLite exception handling. A PostgreSQL, Firebase, or other persistence backend supplies its own repository adapter while routes and compliance logic remain unchanged.

## Secrets

`driftguard_platform.secrets.SecretProvider` resolves secret references. The built-in `env` adapter treats references as environment-variable names. Persisted connector/AI configuration stores references only, never credential values. Production Vault/KMS/Key Vault/Secrets Manager adapters can register the same contract.

## Integrations

`ConnectorConfig` contains non-secret settings plus `secret_refs`. `connector_for()` resolves credentials at construction and uses the existing `ConnectorRegistry`. New integrations implement the existing `Connector` contract and normalize output to `ConnectorRecord` / `SyncResult`.

## AI

The existing `AIProvider` / `AIRegistry` remain authoritative. `AIProviderConfig` adds secret-reference based construction without putting keys into tenant configuration. AI remains non-authoritative for compliance verdicts.

## Extension rule

1. Implement the appropriate provider contract.
2. Register the provider factory.
3. Configure provider name/settings/secret references.
4. Pass contract tests.
5. Do not import the provider from compliance/evaluation domain code.

## Fail closed

Unknown storage/secret/AI/connector providers fail explicitly. Missing secret references fail explicitly. No adapter silently falls back to a different production provider.
