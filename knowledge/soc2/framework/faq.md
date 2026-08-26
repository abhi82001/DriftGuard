---
doc_id: FRW-FAQ
title: SOC 2 FAQ
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
primary_sources: [SRC-AICPA-TSC-2017-R2022, SRC-AICPA-ATC-205, SRC-DG-AUDITOR-PRACTICE]
---

# FAQ

**Is SOC 2 a certification?**
No. It is an attestation examination that produces a report containing a CPA's opinion. There is no certificate and no certifying body. `[SRC-AICPA-ATC-205, tier 1]`

**Can you fail a SOC 2?**
Not in those terms. The auditor issues an unqualified, qualified, adverse, or disclaimer opinion. A report with exceptions and an unqualified opinion is common and is not a failure. `[SRC-AICPA-ATC-205, tier 1]`

**Which trust services categories do we need?**
Security always. The others are elective and should follow the commitments you make to customers — availability if you commit to uptime, confidentiality if you commit to protecting designated confidential information, processing integrity if you commit to accurate processing, privacy if you handle personal information under a privacy notice. `[SRC-AICPA-TSC-2017-R2022, tier 1]`

**How many controls does SOC 2 require?**
None specifically. The criteria state objectives; you select controls that meet them. There are 61 criteria in the 2017 TSC across all five categories (33 common criteria plus 28 category-specific), but criteria are not controls. `[SRC-AICPA-TSC-2017-R2022, tier 1]`

**Do we have to address every point of focus?**
No. Points of focus are illustrative aids. They are not requirements and need not be individually addressed. `[SRC-AICPA-TSC-2017-R2022, tier 1]`

**How long must a Type 2 period be?**
No minimum is prescribed. 3 to 12 months are all seen; enterprise buyers commonly expect 12 months for an established program. This is market expectation, not a rule. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

**Do we need a Type 1 before a Type 2?**
No. A Type 1 is optional and is usually chosen to meet a customer commitment before enough time has elapsed for a Type 2 period. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

**Our cloud provider has a SOC 2. Does that cover us?**
No. Their report covers their controls. You inherit nothing automatically. You must review their report, identify complementary user entity controls, and implement those yourself. `[SRC-AICPA-SOC2-GUIDE, tier 2]`

**What is a bridge letter and is it enough?**
Management's unaudited statement that no material control changes occurred since the report period ended. It carries no assurance and is not evidence of control operation. `[SRC-DG-AUDITOR-PRACTICE, tier 4]`

**Can we remediate an exception before the report is issued?**
You can fix the control, but the deviation occurred during the period and will be reported. Remediation supports the management response and reduces future risk; it does not remove the exception. `[SRC-AICPA-ATC-205, tier 1]`

**Does a SOC 2 report satisfy ISO 27001, HIPAA, or GDPR?**
No. Controls often overlap, and DriftGuard's mapping layer models that overlap, but each framework has its own scope, criteria, and evidence expectations. Overlap reduces work; it does not confer conformity. `[SRC-DG-BEST-PRACTICE, tier 5]`

**Who can perform a SOC 2 examination?**
An independent licensed CPA firm, subject to the AICPA attestation standards. `[SRC-AICPA-ATC-105, tier 1]`
