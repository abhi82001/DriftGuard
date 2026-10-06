# CP013 — actual validation evidence

Source: integrated CP009 ZIP; changes are isolated in this extracted release-candidate folder.

- Baseline: `python -m pytest -q backend/tests knowledge/soc2/tests` -> 119 passed, 4 warnings.
- After fixes: `python -m pytest -q backend/tests knowledge/soc2/tests -W error` -> 128 passed, zero emitted warnings.
- `python -m compileall -q backend/src backend/tests knowledge/soc2` -> succeeded.
- `python knowledge/soc2/validate.py` -> 123 JSON files, 0 errors, 0 warnings.
- Regression suite includes existing real Q3 access-review workbook, CP009 mapping, sufficiency, lineage, consistency and API serialization; added negative upload cases, optional API key and semantic-provider failure checks.

Not performed: penetration testing, authenticated multi-user/tenant isolation testing, production load testing, cloud infrastructure deployment, backup restore, external LLM live testing, full OWASP review or manual SOC 2 auditor UAT. These are release gates, not inferred successes.
