---
doc_id: FRW-COMMON-FINDINGS
title: Common Findings
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
authority_tier_dominant: 4
primary_sources: [SRC-DG-AUDITOR-PRACTICE]
---

# Common Findings

> **Authority notice.** Tier 4 practitioner observation. These are patterns commonly seen, not a defined SOC 2 taxonomy. Frequency claims are qualitative. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

Findings are catalogued in `knowledge/soc2/findings/` as structured records. This document establishes the **categories** and the reasoning patterns behind them.

## Finding categories

| Category key | Meaning |
|---|---|
| `control_absent` | No control exists to address the criterion |
| `design_deficiency` | A control exists but would not meet the criterion even if operating perfectly |
| `operating_deficiency` | Suitably designed, but did not operate as described |
| `evidence_deficiency` | The control may have operated, but cannot be demonstrated |
| `documentation_deficiency` | Policy or description does not reflect actual practice |
| `scope_deficiency` | The control does not cover the full in-scope population or boundary |
| `timeliness_deficiency` | The control operated, but outside its committed timeframe |
| `third_party_deficiency` | The gap sits with a subservice organization or an unaddressed CUEC |

## Recurring patterns

### Access management (CC6 series)
- Terminated users retain access beyond the committed revocation window.
- Access reviews performed but identified issues never closed out.
- Review population drawn from a partial user list, missing service accounts, contractors, or a secondary IdP.
- Privileged access granted without documented approval.
- Shared or generic accounts with no attribution to an individual.

### Change management (CC8)
- Deployments in the change log with no corresponding approval record.
- Emergency changes not retrospectively reviewed.
- Developers able to deploy to production without independent approval, with no compensating detective control.

### System operations and monitoring (CC7)
- Vulnerability scan scope narrower than the asset inventory.
- Remediation SLAs missed with no documented risk acceptance.
- Alerting configured but no evidence anyone triaged the alerts.
- Incident response plan never tested during the period.

### Risk assessment (CC3) and monitoring (CC4)
- Risk assessment performed once at program inception and never refreshed.
- Risk register with no linkage from identified risks to implemented controls.
- Fraud risk not considered — a specific COSO-derived expectation that is easy to overlook. `[SRC-COSO-2013, tier 2]`

### Vendor and third-party risk (CC9)
- Subservice organization SOC 2 reports collected but not reviewed.
- CUECs in a vendor's report never mapped to the organization's own controls.
- Vendor report period leaving an uncovered gap, with no bridge letter or compensating assessment.

### Documentation and control environment (CC1, CC2)
- Policies approved after the examination period began.
- No evidence of security awareness training completion for the full workforce population.
- Control descriptions in the system description not matching how the control actually operates.

## Severity reasoning

DriftGuard scores severity from four inputs, mirroring auditor judgement rather than a fixed label:

1. **Criterion impact** — could the criterion fail to be met?
2. **Pervasiveness** — isolated instance or systemic?
3. **Compensating controls** — is the objective met another way?
4. **Detectability** — would the organization have noticed on its own?
