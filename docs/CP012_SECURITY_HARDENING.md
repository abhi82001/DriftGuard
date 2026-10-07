# CP012 — application-side pilot hardening

Implemented: bounded file reads (5 MiB/file, max 25 files), allowlisted extensions, unsafe filename rejection, basic format checks for PDF/Office, Office ZIP expansion limit, optional shared-secret API gate for `/api/evidence-map`, and safe semantic-provider exception handling. HTTP 413/415/400 replace delayed ingestion errors for rejected uploads. The API secret uses constant-time comparison.

**NOT IMPLEMENTED / DEPLOYMENT BLOCKERS:** enterprise SSO, roles, assessment/tenant isolation, persistent encrypted storage, deletion/retention policy, complete audit logging, global authorization for HTML routes, rate limits, dependency security review, PDF decompression/complexity controls, malware scanning, reverse-proxy multipart body limit, secure hosting and incident-response ownership. Do not expose real sensitive vendor evidence on a public endpoint. Basic file signature checks do not make arbitrary documents safe.

`DRIFTGUARD_API_KEY` is optional and intended for controlled local API testing only. Production must place ALL routes behind an approved authenticated gateway, not rely on this API key alone.
