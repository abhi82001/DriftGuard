# DriftGuard Architecture Lock

This document locks the validated knowledge architecture and the responsibility
boundary between layers. It is authoritative. Future agents must treat the
existing `knowledge/soc2/` schemas, IDs, and relationships as fixed.

## Canonical entities

The knowledge base (`knowledge/soc2/`) defines these record types, each governed
by a schema in `knowledge/soc2/schemas/` and validated by
`knowledge/soc2/validate.py`:

- **criteria** — Trust Services Criteria (`framework/trust_services_criteria.json`)
- **controls** — `SOC2-<criterion>-NNN`
- **evidence** — `EV-<DOMAIN>-NNN`
- **policies** — `POL-<DOMAIN>-NNN`
- **questionnaires / questions** — `QN-<DOMAIN>-NNN` / `QN-<DOMAIN>-NNN-QNN`
- **findings** — `FND-<DOMAIN>-NNN`
- **remediations** — `REM-<DOMAIN>-NNN`
- **mappings** — `MAP-NNNN` (typed relationship edges)
- **semantic conditions** — `SEMCOND-NNNN`
- **evaluation results** — `SEMRES-*` (semantic evaluation result records)

## Responsibility boundary

```text
Knowledge layer        ->  defines compliance meaning
                           (requirements, conditions, findings, relationships)

Evaluation engine      ->  executes deterministic mechanics only
                           (backend/src/evaluation/)

Semantic evaluator     ->  future interpretation layer for free-text answers
                           (not yet implemented)

Application/API/UI     ->  future product layer
                           (not yet implemented)
```

## Locked invariant

```text
KNOWLEDGE DEFINES REQUIREMENTS.
ENGINE EVALUATES REQUIREMENTS.
LLM MAY LATER INTERPRET TEXT.
LLM MUST NEVER INVENT REQUIREMENTS.
```

- Application code **consumes** the knowledge base. It must never silently
  repair, reinterpret, or invent knowledge.
- The gap-signal condition grammar is version **1.0.0**, with exactly three
  operators: `equals`, `in`, `not_includes_all`. There is one grammar; do not
  introduce a second.
- Free-text / semantic conditions are **never guessed** by the deterministic
  engine. They resolve to `SEMANTIC_EVALUATION_REQUIRED`.
- No engine output may assert a compliance verdict, audit opinion, or
  certification. DriftGuard produces readiness signals only.

## Change control

Changes to validated schemas, IDs, relationships, or knowledge semantics require
an explicit architecture migration recorded as a new checkpoint. They must not
be made casually or as a side effect of application-layer work. The validator
(`knowledge/soc2/validate.py`) must always report **0 errors, 0 warnings**.
