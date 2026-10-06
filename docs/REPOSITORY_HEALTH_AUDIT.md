# Repository health audit — CP010–CP013 pilot-hardening pass

Baseline (integrated CP009 archive): 119 pytest tests passed, 4 warnings. Warnings were two deprecated `jsonschema.RefResolver` import warnings and two pytest tests returning integers. Python application remains server-rendered, in-memory, and unauthenticated by default. This is not a complete static-analysis, dependency-vulnerability, penetration-test or privacy assessment.

## Findings and treatment

- HIGH: `/api/evidence-map` and `/analyze` accepted unbounded multipart files into memory, bypassing ingestion's file-count limit. Fixed: bounded reads, 10-file limit, 5 MiB/file, allowlisted extensions, path/filename rejection, PDF signature and Office ZIP structure checks, expanded Office ZIP limit. A reverse proxy must enforce a request-body limit before multipart parsing.
- HIGH: no production-grade identity, RBAC, tenant isolation or durable secure storage. NOT FIXED: external platform design/approval needed. Do not expose this app to real multi-tenant production evidence.
- MEDIUM: API lacked even a shared-secret gate. Added optional `DRIFTGUARD_API_KEY` for `/api/evidence-map` as a local/pilot protection layer. It is NOT enterprise authentication; `/analyze` and other HTML routes remain unauthenticated. A trusted gateway must protect the entire application.
- MEDIUM: optional semantic fallback could propagate provider exceptions. Fixed: bounded proposal input and safe clarification on provider failure. No live LLM connection was added.
- LOW: deprecated JSON Schema resolver. Replaced with `referencing.Registry` and `Draft202012Validator`, consistent with schema declarations.
- LOW: two tests returned integers. Refactored executable checks into `run_*` and pytest wrappers with assertions.
- HIGH functional scope: verified CP009 mapping still covers only QN-ACCESS-001 Q01/Q03–Q06; remaining questions explicitly NOT_EVALUATED. No unapproved evidence business rules were fabricated.

Regression note: one prior test expected a malicious `.exe` upload to be stored as a failed assessment; the hardened boundary now rejects it immediately with HTTP 415. This intentional contract change is tested.
