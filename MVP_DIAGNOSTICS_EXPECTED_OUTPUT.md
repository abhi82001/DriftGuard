# MVP evidence diagnostics — tested expected outputs

Scope: The actual amma uploads were not provided as binary files in this session. The available user-provided **rendered reports** were reviewed. The executable adversarial test transcribes the risk-register header and R-001 row shown in the report, and the second test uses a short synthetic policy. Do not claim these are byte-for-byte tests of the original DOCX/CSV uploads.

## Exact issues identified

- `ENGINE-LOCAL-001`: LOCAL document analysis still uses `DemoClaimExtractor`, a narrow deterministic local rule engine. It is **not** a model-backed semantic pass. Disabling DEMO changes the label, not this extractor.
- `COVERAGE-001`: Only 8 of 29 questions have explicit claim contracts in `QUESTION_SPECS`; the other 21 default to NOT_ESTABLISHED. Their output is *not a full semantic assessment*.
- `CLAIMS-001`: shows recognized claim count; `CLAIMS-002` names uploads from which no supported claims were recognized.
- `EQA-UNSUPPORTED-TYPE`: the tabular validator supports USER_ACCESS_REVIEW only. Risk_Register.csv, Data_Inventory.csv, Data_Deletion_Records.csv and other unsupported files are **unvalidated**, not QA-passed. The report no longer misleadingly lists missing access-review signal groups as if they were universal requirements.
- Risk-register treatment `MFA + quarterly access review` and generic `Review Date=2026-08-15` cannot establish MFA enforcement, completed access-review date, review population, or access removal. Incidental text in unrelated risk/inventory/deletion rows cannot create a claim or clarification for the narrow access/crypto contracts.

## Actual executable results (synthetic/reconstructed inputs)

### A. Risk_Register.csv only (R-001 from supplied report)

```
Documents analyzed: 1
Established: 0
Partially established: 0
Missing evidence (current UI label): 29
Clarification required: 0
Recognized supported claims: 0
Structured Evidence QA: UNCLASSIFIED / unvalidated
Q01 MFA: NOT_ESTABLISHED
Q03 Access-review cadence: NOT_ESTABLISHED
Q04 Identity population: NOT_ESTABLISHED
Q05 Removal tracking: NOT_ESTABLISHED
```

**Interpretation:** 29 is a questionnaire default, not 29 verified failures or 29 completed semantic evaluations. Read the diagnostics card for the exact coverage limitation.

### B. Synthetic Information_Security_Policy.txt plus reconstructed R-001

Policy text: `MFA is required for interactive production administration. User access reviews are required quarterly.`

```
Documents analyzed: 2
Established: 0
Partially established: 2
Missing evidence: 25
Clarification required: 2
Recognized supported claims: 2
Q01 MFA: PARTIALLY_ESTABLISHED (policy requirement/scope only)
Q03 Access-review cadence: PARTIALLY_ESTABLISHED (policy cadence only)
Q04 Identity population: CLARIFICATION_REQUIRED (no population proven)
Q05 Removal tracking: CLARIFICATION_REQUIRED (no removal evidence)
Risk_Register.csv: UNCLASSIFIED / unvalidated
```

The risk row never supplies operating evidence. These are **observed results from running the code**, not an auditor conclusion.

## How to run

```
python -m pytest -q backend/tests knowledge/soc2/tests -W error
python knowledge/soc2/validate.py
python -m compileall -q backend/src
```

## MVP release gate — remaining work

This update fixes false promotion and makes unsupported analysis visible; it does **not** implement comprehensive semantics or validators for risk registers, deletion records, inventories, endpoint policies, etc. Do not present this as fully working general-purpose SOC 2 document intelligence. To validate actual customer files, supply sanitized original binaries and run a golden expected-vs-actual test per artifact. Configure and test a model provider separately if true semantic document interpretation is required. The app currently stores assessments in memory and is not production multi-tenant infrastructure.
