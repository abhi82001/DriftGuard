---
doc_id: FRW-OVERVIEW
title: SOC 2 Overview
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
primary_sources: [SRC-AICPA-TSC-2017-R2022, SRC-AICPA-ATC-205]
---

# SOC 2 Overview

## What SOC 2 is

SOC 2 is an **attestation examination** performed by a licensed CPA firm under the AICPA's attestation standards, in which the practitioner reports on a service organization's controls relevant to one or more **trust services categories**: security, availability, processing integrity, confidentiality, and privacy. `[SRC-AICPA-TSC-2017-R2022, tier 1]`

The examination is assertion-based: management describes its system and asserts that the description is fairly presented and that controls are suitably designed (and, in a Type 2, operated effectively). The practitioner then obtains evidence and issues an opinion on those assertions. `[SRC-AICPA-ATC-205, tier 1]`

## What SOC 2 is not

- **Not a certification.** There is no certificate, no certifying body, and no pass/fail. The output is a report containing an opinion. `[SRC-AICPA-ATC-205, tier 1]`
- **Not a prescribed control list.** The trust services criteria state *objectives*; the service organization selects the controls it believes meet them. Two compliant organizations can have very different control sets. `[SRC-AICPA-TSC-2017-R2022, tier 1]`
- **Not a checklist of points of focus.** Points of focus are illustrative aids, not requirements. `[SRC-AICPA-TSC-2017-R2022, tier 1]`
- **Not a security guarantee.** The opinion covers the described system, for the stated period, subject to inherent limitations.

## Structure of the criteria

The criteria are organised as:

- **Common criteria (CC1–CC9)** — the security category. Always in scope. CC1–CC5 are organised around the 17 COSO internal control principles; CC6–CC9 cover logical and physical access, system operations, change management, and risk mitigation. `[SRC-AICPA-TSC-2017-R2022, tier 1; SRC-COSO-2013, tier 2]`
- **Category-specific additional criteria** — A1 (availability), PI1 (processing integrity), C1 (confidentiality), P1–P8 (privacy), added only when the corresponding category is in scope.

Security must be included in every SOC 2 examination. The other four categories are elective and are chosen based on the service organization's commitments to its customers. `[SRC-AICPA-TSC-2017-R2022, tier 1]`

See `trust_services_criteria.json` for the full criteria index.

## Why organizations pursue SOC 2

Almost always commercial rather than regulatory: enterprise procurement and vendor risk programs require a current SOC 2 Type 2 report before onboarding a vendor that handles their data. SOC 2 is not mandated by any statute. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

## How DriftGuard uses this layer

The knowledge base supplies the compliance semantics that DriftGuard's analysis features depend on: what a criterion is asking for, what evidence plausibly supports it, what typically goes wrong, and what remediation is proportionate. Every assertion carries a source and an authority tier so that the product can distinguish a requirement from a recommendation when it speaks to a customer.
