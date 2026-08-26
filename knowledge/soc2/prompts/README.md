# prompts/

Reserved for prompt specifications used by the future DriftGuard AI engine. **No prompts are authored in this phase** — the AI engine is explicitly out of scope for the foundation.

## What belongs here later

One specification per analysis capability, each declaring which knowledge records it reads, what it is permitted to assert, and how its output is grounded:

| Planned spec | Consumes | Produces |
|---|---|---|
| `gap_detection` | controls, criteria, questionnaire answers, evidence analysis results | observations against finding archetypes |
| `evidence_analysis` | evidence definitions and their `validation_rules` | per-dimension verdicts (existence, relevance, completeness, timeliness, authenticity, sufficiency) |
| `report_parsing` | `framework/report_structure.json` | extracted sections, opinion, CUECs, CSOCs, exceptions |
| `vendor_risk_review` | parsed third-party report plus the customer's own control set | CUEC coverage assessment and residual risk |
| `remediation_guidance` | findings and remediation playbooks | prioritised, sourced remediation plan |
| `compliance_reporting` | the whole graph | narrative report with citations |

## Constraints any prompt written here must carry

These follow from `framework/source_governance.md` and `framework/best_practices.md` and are not negotiable:

1. Ground every assertion in a knowledge record. No answer from model priors about what SOC 2 requires.
2. Surface the authority tier. A tier 5 recommendation must never be rendered in the language of a tier 1 requirement.
3. Never state a requirement without a tier 1 or tier 2 citation.
4. Never call a DriftGuard observation an audit finding, or a DriftGuard score an opinion.
5. Say so when the knowledge base has no basis for an answer, rather than generalising.
6. Respect `false_positive_guidance` on every finding archetype before reporting an observation.
