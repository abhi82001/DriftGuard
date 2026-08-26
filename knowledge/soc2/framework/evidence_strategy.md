---
doc_id: FRW-EVIDENCE-STRATEGY
title: Evidence Strategy
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
primary_sources: [SRC-AICPA-ATC-205, SRC-DG-AUDITOR-PRACTICE, SRC-DG-BEST-PRACTICE]
---

# Evidence Strategy

## Evidence taxonomy

DriftGuard classifies every evidence artifact along these axes. The controlled vocabularies here are normative for `evidence.schema.json`.

**`evidence_type`** — what the artifact is:
`configuration_export`, `system_generated_report`, `log_extract`, `ticket_record`, `signed_document`, `policy_document`, `screenshot`, `attestation`, `scan_result`, `training_record`, `contract`, `third_party_report`, `meeting_record`, `code_artifact`.

**`collection_mode`** — how it is obtained: `automated_api`, `automated_export`, `manual_export`, `manual_capture`, `narrative`.

**`persuasiveness_tier`** — practitioner-weighted strength: `strong` (system-generated, complete, independently reproducible), `moderate` (system-generated but partial, or manual export from a system of record), `weak` (screenshot, self-attestation, narrative). `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## Point-in-time vs period evidence

A **Type 1** is satisfied by point-in-time state. A **Type 2** requires evidence that the control operated throughout the period. Configuration evidence supports a Type 2 only when paired with something demonstrating the configuration was unchanged — change logs, drift monitoring, or periodic re-capture. This pairing requirement is the single most common evidence design error. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## Freshness

Freshness expectations are DriftGuard defaults, derived from control frequency, not SOC 2 rules: `[SRC-DG-BEST-PRACTICE, tier 5]`

| Control frequency | Default freshness window |
|---|---|
| Continuous / automated | 30 days |
| Weekly | 14 days |
| Monthly | 45 days |
| Quarterly | 120 days |
| Annual | 400 days |
| Event-driven | Tied to the event, not the calendar |

Evidence outside its window is flagged as stale — a DriftGuard signal, not an audit finding.

## Coverage principle

One artifact can support several criteria, and one criterion usually needs several artifacts. The mapping layer models this as many-to-many. A criterion supported by only weak evidence is a **coverage risk** even when nothing is missing. `[SRC-DG-BEST-PRACTICE, tier 5]`

## Sensitivity handling

Evidence frequently contains personal data, secrets, or customer data. Each evidence definition carries a `sensitivity` level and `redaction_guidance`. DriftGuard must never instruct a user to submit unredacted secrets, credentials, or production customer records. `[SRC-DG-BEST-PRACTICE, tier 5]`

## Validation dimensions

Evidence analysis evaluates six independent dimensions. All must be modelled separately because a failure in any one is a different finding:

1. **Existence** — the artifact was supplied.
2. **Relevance** — it addresses the control it was submitted for.
3. **Completeness** — it covers the whole population or period.
4. **Timeliness** — it falls within the period and freshness window.
5. **Authenticity** — it is system-generated and attributable.
6. **Sufficiency** — combined with other evidence, it supports a conclusion on the criterion.
