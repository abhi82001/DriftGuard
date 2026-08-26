# DriftGuard SOC 2 Knowledge Base

The compliance knowledge layer for DriftGuard. Everything here is **knowledge**, not application code — no runtime logic, no engine, no UI.

Status: **CC6 and CC7 vertical slices complete.** Structure, schemas, source governance, and full slices for CC6 (Logical and Physical Access Controls) and CC7 (System Operations) are in place. CC1-CC5 and CC8-CC9 are not started.

## Layout

```
knowledge/soc2/
├── framework/         Framework-level knowledge: criteria index, report anatomy,
│                      lifecycle, evidence strategy, glossary, source registry
├── schemas/           JSON Schema definitions governing every record type
├── controls/          Control definitions            (17: CC6.1-CC6.8, CC7.1-CC7.5)
├── evidence/          Evidence type definitions      (18)
├── policies/          Policy definitions             (10)
├── questionnaires/    Assessment questionnaires      (4, 29 questions)
├── findings/          Finding archetypes             (25)
├── remediations/      Remediation playbooks          (25)
├── mappings/          The authoritative relationship graph (323 edges, 3 sets)
├── prompts/           Reserved for the future AI engine; specification only
└── validate.py        Structural, schema, and referential integrity validator
```

## Start here

| To understand | Read |
|---|---|
| What SOC 2 is and is not | `framework/overview.md` |
| The criteria structure | `framework/trust_services_criteria.json` |
| How sourcing works | `framework/source_governance.md`, then `framework/references.json` |
| The data models | `schemas/` — start with `common.defs.json` |
| How entities relate | `mappings/MAPSET-ACCESS-CORE.json`, then `MAPSET-CC6.json`, `MAPSET-CC7.json` |
| Rules for contributing | `framework/best_practices.md` |

## The relationship model

```
criterion ──addresses_criterion──┐
                                 ▼
                              control ──supported_by_evidence──▶ evidence
                                 │  ├──documented_by_policy────▶ policy
                                 │  └──assessed_by_question───▶ question
                                 ▼                                 │
                              finding ◀──indicates_finding─────────┘
                                 │
                                 └──remediated_by──▶ remediation ──verified_by_evidence──▶ evidence
```

Every edge is bidirectional via its declared inverse, so the graph answers questions from either end: *which evidence supports this control* and *which controls does this evidence support* are the same edge read in opposite directions.

The relationship vocabulary is **global**, not per-file. Mapping sets are split by vertical slice for reviewability; the validator unions the declared types across all sets and errors if two sets define the same type name differently. Convenience references on entity records are checked against the graph in both directions.

## Two axes on findings

`finding_category` describes the **nature** of a deficiency (design, operating, evidence, scope, timeliness, documentation, third-party, absent).

`observation_class` describes **how strong a conclusion the available information supports** — `missing_evidence`, `insufficient_evidence`, `control_design_gap`, `control_operating_gap`, `potentially_ineffective_control`, `informational_observation`. Every archetype also carries `conclusion_rules` stating what DriftGuard may and may not assert, and what would justify escalating or de-escalating the class.

The absence of an artifact is `missing_evidence`. It is never, by itself, a control failure.

## Non-negotiables

1. **Never invent a requirement.** "Must" and "required" need a tier 1 citation. Recommendations stay recommendations.
2. **Never reproduce copyrighted criteria text.** Reference identifiers; write original interpretation.
3. **IDs are permanent.** Never reuse, never renumber. Deprecate with `status: deprecated` and `superseded_by`.
4. **One fact, one home.** Cross-reference by ID. Bibliographic detail exists only in `framework/references.json`.
5. **Never call an absent artifact a control failure.** Set `observation_class` to what the evidence supports and let `conclusion_rules` govern the language.
6. **Validation passes before merge.**

## Validating

```bash
pip install jsonschema
python3 knowledge/soc2/validate.py
```

Exit code 0 means clean. Warnings are advisory; errors block.
