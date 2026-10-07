# DriftGuard CP029 test readiness

The repository is ready for acceptance testing, not declared production-ready.

Required acceptance gates:

1. Full regression suite passes.
2. Aggregate runner exits zero.
3. Latest 58-file external pack processes without errors.
4. DPDP consent/rights/processor CSVs classify to privacy roles.
5. API smoke succeeds for UI/OpenAPI and `/api/v1` capability endpoints.
6. Optional live OpenAI smoke test is performed only with an operator-provided server-side key; normal tests never require paid/network AI.
7. Enterprise deployment remains blocked until persistent tenant storage, secrets management, production auth/RBAC and operational infrastructure are selected and tested.
