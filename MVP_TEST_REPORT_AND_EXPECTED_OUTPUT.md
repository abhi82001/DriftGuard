# DriftGuard MVP: uploaded CP008 scenarios + clear-results regression

## What was actually tested

The uploaded `DriftGuard-CP008-evidence-semantics-fix(1).zip` contains a 120-case language benchmark and six MFA format fixtures. These were merged into the newer `DriftGuard-MVP-diagnostics-validated` baseline, rather than replacing the newer CP009–CP013 functionality with the older CP008 repository.

Executed locally:

- `python -m pytest -q backend/tests knowledge/soc2/tests -W error`: **136 passed**.
- `python knowledge/soc2/validate.py`: **123 JSON files, 0 errors, 0 warnings**.
- `python -m compileall -q backend/src`: **passed**.
- CP008 benchmark: **120 cases** (100 positive / 20 negative); **100/100 annotated targets recovered**; **0/20 negative cases emitted material facts**. This is a narrow, fixture-specific metric, not generalized semantic accuracy.
- Six fixtures (TXT, MD, CSV, XLSX, DOCX and text PDF) pass format-parity/provenance test.
- Added UI regression on reconstructed `Risk_Register.csv` row from the user's displayed report.

## Expected UI: reconstructed Risk_Register.csv only, LOCAL

The risk treatment entry `MFA + quarterly access review` and generic risk review date `2026-08-15` must **not** become MFA enforcement, completed access review, or reviewed identity populations.

- Files received: **1**
- Requirements with evaluation rules: **8**
- Established: **0**
- Partially established: **0**
- Needs clarification: **0**
- No supported fact found (within 8 implemented rules): **8**
- Not yet supported by this engine: **21**
- Evidence QA: **1 unclassified / unvalidated artifact**, **0 structured exceptions** (not a pass).
- Diagnostics: ENGINE-LOCAL-001, COVERAGE-001, CLAIMS-001, CLAIMS-002, EQA-UNSUPPORTED-TYPE.

The old internal `DocumentAssessment.counts` still totals 29 `NOT_ESTABLISHED` for backwards compatibility. The **results page** now separates 8 evaluated/no recognized fact from 21 not evaluated. Do not use that legacy count as a coverage or completeness KPI.

## Changes to the human interface

- Replaced the misleading generic `29 missing evidence` overview with separate **implemented**, **not yet supported**, and **no supported fact found** categories.
- Added a plain-language `How to read this assessment` section before summary cards.
- Added `Why did I get these results?` diagnostics, with explanations and stable diagnostic codes.
- Unimplemented questions appear in a separate collapsible list rather than being displayed as evaluated missing material.
- Wider content area and horizontally scrollable result tables.

## Remaining MVP boundaries (not concealed)

- LOCAL/DEMO extraction is deterministic, **not a live semantic LLM**.
- 8/29 questionnaire questions have explicit evaluation contracts; the other 21 are not evaluated by this extractor.
- Structured Evidence QA currently does not validate risk registers, data inventories or data-deletion records. These must remain unclassified until type-specific schemas and checks are implemented.
- The actual amma original CSV/DOCX binaries were not in the supplied test ZIP; the risk row is reconstructed from the displayed report. The CP008 benchmark fixtures were tested from their actual uploaded bytes.
- Do not present this as an enterprise-ready auditor or compliance certification system.

## Running

From the extracted `driftguard_release` folder:

```bash
python -m pip install -r backend/requirements.txt
python -m pip install httpx jsonschema referencing
python -m pytest -q backend/tests knowledge/soc2/tests -W error
python knowledge/soc2/validate.py
export DRIFTGUARD_DEMO_MODE=0
python -m uvicorn backend.src.app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and upload a test file. Do not run the older CP008 ZIP as the release; it is the **scenario source**, not the latest application.
