---
doc_id: FRW-AUDIT-PROCESS
title: How the Examination Is Actually Performed
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
primary_sources: [SRC-AICPA-ATC-205, SRC-AICPA-SOC2-GUIDE, SRC-DG-AUDITOR-PRACTICE]
---

# The Examination Process

Where `audit_lifecycle.md` describes the client journey, this document describes what the **service auditor** does. DriftGuard's analysis quality depends on modelling the auditor's reasoning, not just the control list.

## 1. Acceptance and independence

The practitioner evaluates independence, competence, and whether the subject matter and criteria are suitable and available to intended users. `[SRC-AICPA-ATC-105, tier 1]`

## 2. Understanding the system and risks

The auditor develops an understanding of the system, the service commitments and system requirements, and the risks that threaten the criteria being met. Control selection follows from this risk understanding.

## 3. Evaluating suitability of design

For each in-scope criterion, the auditor asks: *if the identified controls operated as described, would the criterion be met?* A design conclusion is reached before any operating-effectiveness testing. A control that is well operated but poorly designed still fails. `[SRC-AICPA-ATC-205, tier 1]`

## 4. Testing operating effectiveness (Type 2)

Test procedures, roughly in ascending order of persuasiveness:

1. **Inquiry** — insufficient on its own. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`
2. **Observation** — limited to the moment observed.
3. **Inspection** — of documents, tickets, configurations, logs. The workhorse.
4. **Reperformance** — the practitioner independently re-executes the control.

Sampling depends on control frequency and nature. Automated, configuration-based controls may be tested with a single sample plus evidence that the configuration was unchanged through the period; manual recurring controls are sampled across the period. Sample sizes are firm methodology, not a published requirement — DriftGuard must not state specific sample sizes as SOC 2 rules. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## 5. Population completeness and accuracy

Before sampling, the auditor must be satisfied the population is complete and accurate. A system-generated list is challenged on how it was generated, whether filters were applied, and whether it can be reconciled. This is the most common cause of evidence rejection in practice. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## 6. Evaluating deviations

An identified deviation is assessed for cause, pervasiveness, and whether compensating controls address the criterion. The conclusion determines whether the deviation is reported as an exception with a clean opinion, or escalates to a qualified or adverse opinion. `[SRC-AICPA-ATC-205, tier 1]`

## 7. Forming and expressing the opinion

The opinion addresses description fairness, design suitability, and (Type 2) operating effectiveness. See `report_structure.json` for opinion types. `[SRC-AICPA-ATC-205, tier 1]`

## What this implies for DriftGuard

- Gap detection must evaluate **design** and **operation** as separate dimensions.
- Evidence analysis must assess **population completeness**, not just whether a document exists.
- Severity scoring should follow the auditor's logic — cause, pervasiveness, compensating controls — rather than a flat criticality label.
