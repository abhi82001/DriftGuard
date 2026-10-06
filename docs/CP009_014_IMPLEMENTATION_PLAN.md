# CP009–CP014 implementation audit and continuation plan

Verified baseline on this copied Phase 1 tree: `PYTHONPATH=backend/src pytest -q backend/tests` → 140 passed (the earlier 142 count is not reproducible with this invocation). The original evidence pack has 52 ingestible evidence files and 26 tabular artifacts.

- CP009: `backend/src/documents.py` contains eight executable `QUESTION_SPECS`; `knowledge/soc2/questionnaires` has 29 questions. The attached matrix identifies the 21 missing specifications. Their expected evidence IDs alone are **not** executable sufficiency conditions. Define source-role, period and population conditions before enabling them.
- CP010: `backend/src/evidence/structured_registry.py` contains 25 header-based register signatures; `user_access_review.py` retains the specialized access-review path. This checkpoint adds conservative domain checks for risk, deletion, firewall and vulnerability records. Most remaining schemas only have generic quality checks.
- CP011: `backend/src/claims.py` remains a narrow deterministic extractor; the semantic evaluation provider under `evaluation/providers/claude.py` is not integrated as general document extraction. A configured provider and grounded extraction schema are still needed.
- CP012: `backend/src/evidence/pipeline.py` returns tabular QA separately; no general validated cross-document join or 29-requirement sufficiency engine exists.
- CP013: Existing `backend/src/app.py` reporting must be updated after the actual evidence semantics exist.
- CP014: Run individual, domain and whole-pack tests; construct independently adjudicated expected outcomes rather than copying engine results. Test a clean Windows environment separately.

**Critical:** Do not promote register metadata (e.g. Risk Register Review Date) to proof of an access review. Do not label this build FINAL.
