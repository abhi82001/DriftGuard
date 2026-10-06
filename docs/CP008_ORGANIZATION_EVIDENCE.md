# CP008 Organization Evidence Operations

The CP008 backbone now exposes an organization-facing portfolio view via
`build_organization_view(EvidenceAnalysis)`.

It intentionally does **not** decide SOC 2 compliance. It reduces evidence-team
manual work by producing:

- an evidence inventory summary;
- a prioritized human-review/action queue;
- ingestion and validation follow-ups;
- cross-artifact variance detection for like-for-like facts;
- a reusable-concept index showing evidence concepts supported by multiple files.

Safety boundaries:

- policy statements are not compared as if they were implementation evidence;
- differing values are surfaced for review, not automatically resolved;
- unclassified files with grounded facts remain evidence observations and are
  queued for classification instead of discarded;
- missing material remains an evidence gap, not a control failure.

Future checkpoints can attach control/question mappings, period/freshness rules,
and evidence requests to this portfolio layer without changing CP006/CP007.
