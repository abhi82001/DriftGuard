# CP015 Security Review

Implemented and tested: bounded per-file upload reads (5 MB); 25-file external request limit; aggregate request bound; extension plus PDF/OOXML structural verification; path/filename rejection; OOXML expanded-size/member-count checks; active/externally-linked OOXML rejection; malformed parser fail-closed behavior; spreadsheet formula neutralization in extracted CSV/XLSX cells; prompt-injection defenses in CP012; bounded/TTL assessment state; privacy-safe lifecycle logging that excludes evidence text/excerpts; optional constant-time API-key comparison; HTML escaping throughout server-rendered evidence surfaces.

No archive upload type is supported, so generic ZIP archive ingestion is not exposed. DOCX/XLSX are ZIP containers and receive expanded-size/member-count checks.

Remaining security blocker for production deployment: browser/manual assessment state is process-local and the current MVP has no authenticated user/tenant identity layer. Assessment IDs are high-entropy but are not a substitute for authorization. Deploy behind an authenticated perimeter and add durable tenant-scoped storage before multi-tenant production use.
