---
doc_id: FRW-BEST-PRACTICES
title: DriftGuard Best Practices
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
authority_tier_dominant: 5
primary_sources: [SRC-DG-BEST-PRACTICE]
---

# DriftGuard Best Practices

> **Authority notice.** Everything in this document is **tier 5 DriftGuard opinion** unless a higher-tier source is cited inline. None of it is a SOC 2 requirement.

## Program practices (advice DriftGuard gives customers)

1. **Scope narrowly, then expand.** Security-only first period; add categories once the program is stable.
2. **Design the evidence before the control goes live.** If you cannot name the artifact and the system that produces it, the control will fail its evidence test even if it works.
3. **Automate the population, not just the control.** The completeness of the list is what auditors challenge.
4. **Keep periods contiguous.** A gap between report periods is visible to every customer that reads both.
5. **Map CUECs from vendor reports into your own control set** the moment you receive the report, not at renewal.
6. **Review policies annually with recorded approval.** Version history is cheap; reconstructing it is not.
7. **Treat risk acceptance as a first-class artifact,** with owner, rationale, authoriser, and expiry.

## Knowledge-authoring practices (rules for this repository)

These are binding on anyone or anything writing into `knowledge/soc2/`.

1. **Never invent a requirement.** If a statement uses "must" or "required", it carries a tier-1 citation or it does not ship.
2. **Separate requirement from recommendation** in wording, not just in metadata. "The criteria state…" vs "auditors commonly expect…" vs "DriftGuard recommends…".
3. **Do not reproduce copyrighted criteria text.** Reference identifiers; write DriftGuard's own interpretation.
4. **One fact, one home.** Cross-reference by ID rather than restating. Bibliographic detail lives only in `references.json`.
5. **IDs are permanent.** Never reuse or renumber an ID. Deprecate with `status: deprecated` and `superseded_by`.
6. **Every record is versioned** with `version`, `last_reviewed`, and `status`.
7. **Mark uncertainty explicitly** with `verification_status: needs_verification` rather than hedging in prose.
8. **JSON stays valid and schema-conformant.** Validation runs before merge.
9. **Prefer a small validated foundation** over volume. Unreviewed content is a liability in a compliance product.

## Product behaviour rules

- Never tell a user they are "SOC 2 certified" or "SOC 2 compliant" as a state DriftGuard can confer.
- Never present a DriftGuard gap as an audit finding; only a service auditor issues findings.
- Always disclose the authority tier behind an assertion when a user asks why.
- When the knowledge base lacks a basis for an answer, say so rather than generalising.
