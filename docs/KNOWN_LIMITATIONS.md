# Known Limitations

1. Mandatory Chromium E2E is blocked in this sandbox by `ERR_BLOCKED_BY_ADMINISTRATOR`; local execution remains required.
2. Assessment state is bounded and TTL-controlled but process-local; restart loses active assessments and multi-worker state is not shared.
3. There is no first-party user authentication/tenant authorization layer. Do not expose the MVP directly as a multi-tenant Internet service; use an authenticated perimeter until tenant-scoped persistence/authorization is implemented.
4. Live semantic-provider performance/availability was not measured because no provider credentials were configured. Offline acceptance explicitly reports SEMANTIC_UNAVAILABLE.
5. Public upload requests remain limited to 25 files/5 MB each. The internal processing pipeline was benchmarked to 100 files.
6. DriftGuard produces evidence-readiness observations, not a SOC 2 audit opinion, certification, or compliance verdict.
