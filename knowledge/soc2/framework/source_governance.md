---
doc_id: FRW-SOURCE-GOVERNANCE
title: Source Governance Convention
version: 0.1.0
last_reviewed: 2026-08-11
status: draft
structural_note: "Added beyond the required Phase 1 file list. Reason recorded in metadata.json under structure_decisions."
primary_sources: [SRC-DG-BEST-PRACTICE]
---

# Source Governance Convention

Phase 6 of the DriftGuard knowledge charter requires that every factual compliance claim be traceable. This document defines how. The source registry itself is `references.json`.

## The five authority tiers

| Tier | Key | May be stated as | Example source |
|---|---|---|---|
| 1 | `authoritative_requirement` | "The criteria state…", "is required" | TSP Section 100; AT-C 205 |
| 2 | `official_guidance` | "AICPA guidance explains…" | AICPA SOC 2 Guide; DC 200; COSO 2013 |
| 3 | `industry_guidance` | "NIST/ISO/CIS describes…" | SP 800-53 r5; ISO 27001; CIS v8 |
| 4 | `auditor_interpretation` | "Auditors commonly expect…" | DriftGuard practice notes |
| 5 | `driftguard_best_practice` | "DriftGuard recommends…" | DriftGuard opinion |

Full definitions and citation obligations are in `references.json` under `authority_tiers`.

## Citation mechanics

**In JSON records** — a `sources` array of `source_id` strings, plus optional per-assertion `source_refs` objects:

```json
"sources": ["SRC-AICPA-TSC-2017-R2022"],
"source_refs": [
  {
    "source_id": "SRC-AICPA-TSC-2017-R2022",
    "locator": "TSC CC6.1",
    "authority_tier": 1,
    "supports": "criterion_identity"
  }
]
```

**In Markdown** — an inline trailing citation: `` `[<source_id>, tier N]` ``. Documents that are predominantly one tier carry an `authority_tier_dominant` front-matter key and an authority notice at the top.

## Verification status

Every source and every record carries a `verification_status`:

| Value | Meaning |
|---|---|
| `verified` | Checked against the source on `verified_on` |
| `needs_verification` | Believed correct, not yet checked against primary text — **must not** be surfaced to customers as authoritative |
| `interpretation` | Practitioner judgement; no external verification applicable |
| `opinion` | DriftGuard recommendation; no external verification applicable |
| `disputed` | Sources conflict; requires resolution before use |

## Hard rules

1. **Never invent a regulatory or compliance requirement.** If no tier-1 or tier-2 source supports it, it is not a requirement.
2. **Never promote a tier.** A recommendation does not become a requirement because it is widely followed.
3. **Never reproduce copyrighted criteria or standard text.** Cite identifiers; write original interpretation.
4. **Never cite a source that does not actually contain the claim.** A plausible-looking citation is worse than none.
5. **Prefer the primary source.** Cite TSP Section 100, not a blog post about it.
6. **Mark uncertainty in metadata**, not in prose hedging.
