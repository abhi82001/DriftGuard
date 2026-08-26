---
doc_id: FRW-AUDIT-LIFECYCLE
title: SOC 2 Audit Lifecycle
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
primary_sources: [SRC-AICPA-ATC-205, SRC-DG-AUDITOR-PRACTICE]
---

# SOC 2 Audit Lifecycle

The lifecycle below is the **service organization's** journey. It is practitioner-observed sequence, not a prescribed process — the attestation standards govern the examination itself, not how a company prepares for it. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## Stage 1 — Scoping

Decide which trust services categories apply, which systems and products are inside the boundary, which subservice organizations are involved, and whether they will be carved out or included. Scoping errors are expensive later: boundary changes mid-period can invalidate accumulated evidence.

Key outputs: system boundary definition, category selection, subservice organization inventory, target report type and period.

## Stage 2 — Readiness assessment / gap analysis

Compare the current control environment against each in-scope criterion. Produce a gap list with owners and target dates. This is where DriftGuard's gap detection operates.

Key outputs: gap register, remediation plan, evidence inventory.

## Stage 3 — Remediation

Implement or fix controls, write or update policies, stand up the evidence-generating mechanisms (ticketing, logging, review cadences). Controls implemented late in a period will have thin populations.

## Stage 4 — Observation period (Type 2 only)

Controls operate and generate evidence. The examination period begins. Changes to controls during the period must be tracked and disclosed; a control replaced mid-period may need to be tested in both forms.

## Stage 5 — Fieldwork

The auditor requests populations, selects samples, inspects evidence, interviews control owners, and observes processes. Requests arrive in waves; incomplete or inconsistent responses drive most schedule slippage.

## Stage 6 — Exception handling and management response

Deviations identified in testing are discussed. Management may provide context or a response for the unaudited "other information" section. Exceptions cannot be retroactively remediated out of the report — the period has already elapsed.

## Stage 7 — Reporting

The auditor drafts the report, management finalises its assertion and system description, and the report is issued with an opinion.

## Stage 8 — Continuous operation and next period

Controls keep running; the next period typically begins the day after the prior one ends to avoid coverage gaps. Gaps between consecutive report periods are visible to customers and are a common vendor-risk objection. `[SRC-DG-BEST-PRACTICE, tier 5]`

## DriftGuard entry points

| Stage | DriftGuard capability |
|---|---|
| 1 Scoping | Category and boundary advisory |
| 2 Readiness | Gap detection, control catalog mapping |
| 3 Remediation | Remediation guidance, policy drafting support |
| 4 Observation | Evidence freshness monitoring, drift detection |
| 5 Fieldwork | Evidence analysis, request-list response support |
| 7 Reporting | Report parsing, compliance reporting |
| 8 Continuous | Vendor risk review of third-party reports |
