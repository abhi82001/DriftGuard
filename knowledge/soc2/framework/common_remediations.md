---
doc_id: FRW-COMMON-REMEDIATIONS
title: Common Remediations
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
authority_tier_dominant: 5
primary_sources: [SRC-DG-BEST-PRACTICE, SRC-DG-AUDITOR-PRACTICE]
---

# Common Remediations

> **Authority notice.** Predominantly tier 5 DriftGuard recommendation. These are proportionate approaches, not required controls. The service organization chooses its own controls. `[SRC-DG-BEST-PRACTICE, tier 5]`

Remediations are catalogued in `knowledge/soc2/remediations/`. This document establishes the model.

## Remediation dimensions

Every remediation record specifies:

- **`remediation_type`**: `implement_control`, `redesign_control`, `improve_operation`, `improve_evidence`, `update_documentation`, `expand_scope`, `automate`, `accept_risk`.
- **`effort`**: `low` / `medium` / `high` (relative, not hours).
- **`durability`**: `tactical` (closes this finding) vs `structural` (prevents recurrence).
- **`verification_method`**: how DriftGuard confirms the remediation actually landed.

## The tactical/structural pairing

Most findings need both. Removing one stale account is tactical; automating deprovisioning from the HR system is structural. DriftGuard should surface both and be explicit about which closes the immediate exception and which prevents recurrence. `[SRC-DG-BEST-PRACTICE, tier 5]`

## Important limitation: past-period findings

An exception that occurred during an elapsed examination period **cannot be remediated away**. The deviation happened and will be reported. Remediation reduces future risk and supports the management response; it does not remove the finding. DriftGuard must state this plainly rather than implying a fix erases the exception. `[SRC-AICPA-ATC-205, tier 1]`

## Common structural remediations by theme

| Theme | Structural remediation |
|---|---|
| Access drift | HR-system-triggered automated provisioning/deprovisioning; SSO consolidation |
| Access review burden | Tooling that pulls a complete, reconciled entitlement population and tracks closure of flagged items |
| Change control | Branch protection plus required approval enforced in the pipeline, so the control cannot be bypassed |
| Vulnerability SLAs | Asset inventory as the authoritative scan scope; ticket auto-creation with SLA clocks; documented risk-acceptance workflow |
| Evidence fragility | Scheduled automated evidence collection into a dated repository |
| Policy staleness | Annual review cycle with recorded approval and version history |
| Vendor risk | Vendor register with report expiry tracking and CUEC-to-control mapping |

## Risk acceptance

Accepting a risk is a legitimate outcome, not a failure — but it must be documented, authorised at an appropriate level, time-bounded, and revisited. An undocumented decision not to act is a finding; a documented one is a control-environment artifact. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`
