---
doc_id: FRW-AUDITOR-EXPECTATIONS
title: Auditor Expectations
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
authority_tier_dominant: 4
primary_sources: [SRC-DG-AUDITOR-PRACTICE, SRC-AICPA-SOC2-GUIDE]
---

# Auditor Expectations

> **Authority notice.** This document is predominantly **tier 4 auditor interpretation**. Nothing here is a SOC 2 requirement. Expectations vary by firm, engagement, and risk assessment. DriftGuard must present this material as "auditors commonly expect", never as "SOC 2 requires". `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## What makes evidence persuasive

- **System-generated over human-assembled.** An export from the system of record beats a spreadsheet a person maintained.
- **Complete populations, demonstrably so.** The auditor needs to know how the list was produced and that nothing was filtered out.
- **Timestamped and attributable.** Who did what, when, verifiable independently of the person's own account.
- **Contemporaneous.** Evidence produced when the control ran, not reconstructed during fieldwork.
- **Independently reproducible.** The auditor could obtain the same artifact themselves.

## Recurring points of auditor challenge

| Area | What is commonly probed |
|---|---|
| Access reviews | Was the user list complete? Was it reconciled to HR/IdP? Were flagged items actually actioned, and when? |
| Terminations | Time from termination to access revocation, measured against the stated commitment |
| Change management | Are emergency changes tracked, approved after the fact, and reconciled to the deployment log? |
| Vulnerability management | Does the scan scope cover the full asset inventory? Are SLAs met, and how are exceptions approved? |
| Incident response | Was the plan tested? Did real incidents follow the documented process? |
| Vendor management | Were subservice organization reports actually reviewed, and were CUECs addressed? |
| Backups | Were restorations tested, not just backups executed? |

## Signals that reduce auditor confidence

- Screenshots without system context, timestamps, or scope indicators.
- Policies approved the week fieldwork started, with a period that began months earlier.
- Reviews with no evidence of follow-through on identified issues.
- Populations that cannot be reconciled to an authoritative source.
- Control descriptions written in the report that do not match how the control actually runs.

## Screenshots specifically

Screenshots are accepted in practice for configuration evidence, but weakly. They are stronger when they include the URL or console context, a visible timestamp, the account or tenant identifier, and the full scope rather than a cropped fragment. Where an API export or configuration-as-code artifact exists, it is preferred. `[SRC-DG-AUDITOR-PRACTICE, tier 4; SRC-DG-BEST-PRACTICE, tier 5]`

## The design-vs-operation distinction

Auditors separate two questions and DriftGuard should too:

1. **Design** — would this control, if it operated as described, satisfy the criterion?
2. **Operation** — did it in fact run as described, every time it should have, throughout the period?

A control can fail either independently. Conflating them produces misleading gap reports.
