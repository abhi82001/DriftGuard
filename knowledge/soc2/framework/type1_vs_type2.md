---
doc_id: FRW-TYPE1-VS-TYPE2
title: SOC 2 Type 1 vs Type 2
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
primary_sources: [SRC-AICPA-ATC-205, SRC-AICPA-TSC-2017-R2022]
---

# Type 1 vs Type 2

| Dimension | Type 1 | Type 2 |
|---|---|---|
| Opinion basis | As of a specified date | Throughout a specified period |
| Description fairly presented | Yes | Yes |
| Suitability of design | Yes | Yes |
| Operating effectiveness | **No** | **Yes** |
| Tests of controls with results (Section 4) | No | Yes |
| Sampling over a population | Not applicable | Central to the engagement |
| Typical evidence | Configuration state, approved policies, system settings at a point in time | Populations and samples spanning the period |

`[SRC-AICPA-ATC-205, tier 1]`

## Practical consequences

**A Type 1 cannot demonstrate that a control ran.** It shows the control existed and was designed appropriately on one date. A customer relying on a Type 1 for assurance about ongoing operation is misreading the report. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

**Period length is an engagement decision.** The criteria do not prescribe a minimum period for a Type 2. Periods of 3, 6, or 12 months are all seen; enterprise buyers commonly expect 12 months once a program is established, and a short first period followed by annual 12-month periods is a common trajectory. This is market practice, not a requirement. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

**A Type 1 is optional.** Nothing requires an organization to do a Type 1 before a Type 2. It is chosen when a customer commitment lands before enough time has elapsed to observe controls operating. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## DriftGuard analysis rules

- When ingesting a report, always resolve report type before scoring assurance. Type 1 findings must never be presented with the confidence of Type 2 findings.
- A Type 1 followed by no Type 2 within a reasonable interval is a vendor risk signal. `[SRC-DG-BEST-PRACTICE, tier 5]`
- Coverage gaps between the end of a report period and the present are real gaps. A bridge letter narrows the communication gap but supplies no assurance. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`
