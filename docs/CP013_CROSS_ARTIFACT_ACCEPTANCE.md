# CP013 Cross-Artifact Evidence Graph — Acceptance Report

## Status
PASS for the implemented CP013 graph/reconciliation acceptance gate. Cross-artifact observations are evidence review signals, never SOC 2 conclusions.

## Architecture
`backend/src/evidence/graph.py` adds provenance-bearing `GraphNode`, `GraphEdge`, `GraphObservation`, and `EvidenceGraph` models. Joins are exact or conservative normalized identifiers only; no fuzzy matching is performed. Hostname/FQDN normalization strips only the DNS suffix. Identifier namespaces are checked before joins, and ambiguous one-to-many identifiers are surfaced rather than collapsed.

The web `/analyze` path builds the graph from recognized tabular artifacts and the results page renders relationship coverage and review observations with source locators.

## Relationships represented
The registry contains explicit rules for HR↔IdP, IdP↔access review, access review↔remediation, termination↔IdP, asset↔EDR, asset↔disk encryption, asset↔vulnerability, data inventory↔deletion, firewall baseline↔export, vulnerability↔ticket, incident↔postmortem, DR plan↔test, asset↔backup execution, and risk↔treatment/remediation. A relationship is not executed when compatible explicit identifiers are absent; DriftGuard records that as unsupported rather than guessing.

CP011 continues to reconcile narrative DR-plan↔DR-test objectives because those facts are not tabular register entities. CP009/CP010 continue to reconcile policy/design versus operating evidence at questionnaire-contract level.

## Contradiction rules
- asset inventory expects EDR while endpoint evidence says not installed → `CROSS-ARTIFACT-CONFLICT`
- termination evidence records disabled/revoked while IdP records active → `CROSS-ARTIFACT-CONFLICT`
- closed remediation ticket while linked risk/vulnerability remains open → `CLOSURE-CONFLICT`

Coverage gaps remain `NEEDS_REVIEW`, not failures.

## Tests
- CP013 focused graph tests: 8 passed
- Complete DriftGuard suite: 460 passed
- Python compilation: PASS

Focused cases include exact joins, hostname/FQDN normalization, incompatible/fuzzy-match prevention, missing entities, one-to-many ambiguity, coverage arithmetic, provenance chains, HR↔IdP, EDR contradiction, and termination↔IdP contradiction.

## Original 52-file pack
- 52/52 files ingest
- 26 structured artifact types classified
- questionnaire result unchanged from CP012: 0 Established, 8 Partial, 17 Not Established, 3 Clarification, 1 Conflict, 0 Not Evaluated
- graph results are reported separately and do not inflate questionnaire status

The pack intentionally uses incompatible identifiers in several domains (for example HR employee IDs versus IdP user IDs). DriftGuard does not infer those mappings from names. This is a deliberate false-positive prevention rule.

## Remaining limitations
- No fuzzy/person-name identity resolution. A mapping artifact or shared authoritative identifier is required.
- Several listed relationships cannot execute on the synthetic pack because the corresponding artifacts do not expose a shared explicit identifier.
- Narrative policy↔operation and DR plan↔test reasoning remain in the existing grounded questionnaire/CP011 layers rather than being duplicated into the tabular graph.
- Graph persistence is in-memory per assessment; no external graph database is required for the MVP.
