#!/usr/bin/env python3
"""
DriftGuard SOC 2 knowledge base validator.

Checks, in order:
  1. Required directory structure exists.
  2. Every .json file parses.
  3. Every instance record validates against its schema.
  4. Every ID is unique and matches its declared convention.
  5. Every cross-record reference resolves (controls, evidence, policies,
     questions, findings, remediations, criteria, sources).
  6. Mapping edges are well-formed, use declared relationship types, and are
     consistent with the convenience references carried on entity records.
  7. Every record carries at least one source, and cited sources exist.
  8. No duplicate concepts (same name registered under two IDs).

Run:  python3 knowledge/soc2/validate.py
Exit code 0 = pass, 1 = errors found. Warnings do not fail the run.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from jsonschema import Draft7Validator, RefResolver

ROOT = Path(__file__).resolve().parent
SCHEMA_BASE = "https://driftguard.io/schemas/soc2/"

REQUIRED_DIRS = [
    "framework", "controls", "evidence", "policies", "questionnaires",
    "findings", "remediations", "mappings", "prompts", "schemas",
]

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# ---------------------------------------------------------------- 1. structure
def check_structure() -> None:
    for d in REQUIRED_DIRS:
        if not (ROOT / d).is_dir():
            err(f"structure: required directory missing: knowledge/soc2/{d}/")


# ------------------------------------------------------------------- 2. parse
def load_all_json() -> dict[Path, dict]:
    docs: dict[Path, dict] = {}
    for path in sorted(ROOT.rglob("*.json")):
        try:
            docs[path] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            err(f"json: {rel(path)}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}")
    return docs


# ------------------------------------------------------------------ 3. schema
def build_validators() -> dict[str, Draft7Validator]:
    schema_dir = ROOT / "schemas"
    store: dict[str, dict] = {}
    for path in schema_dir.glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        store[SCHEMA_BASE + path.name] = schema

    validators: dict[str, Draft7Validator] = {}
    for name, schema in store.items():
        short = name.rsplit("/", 1)[1]
        if short == "common.defs.json":
            continue
        resolver = RefResolver(base_uri=name, referrer=schema, store=store)
        validators[short] = Draft7Validator(schema, resolver=resolver)
    return validators


SCHEMA_FOR_RECORD_TYPE = {
    "control": "control.schema.json",
    "evidence": "evidence.schema.json",
    "policy": "policy.schema.json",
    "questionnaire": "questionnaire.schema.json",
    "finding": "finding.schema.json",
    "remediation": "remediation.schema.json",
    "mapping_set": "mapping.schema.json",
    "source_registry": "source.schema.json",
    "semantic_condition": "semantic_condition.schema.json",
    "semantic_evaluation_result": "semantic_evaluation_result.schema.json",
}

# Record types that are machine output or registries rather than sourced knowledge.
UNSOURCED_RECORD_TYPES = {"mapping_set", "source_registry", "semantic_evaluation_result"}

PROHIBITED_VERDICTS = [
    "SOC2_FAILED", "SOC2_PASSED", "COMPLIANT", "NON_COMPLIANT", "CERTIFIED",
    "AUDIT_OPINION", "QUALIFIED_OPINION", "UNQUALIFIED_OPINION",
]


def check_semantics(docs: dict[Path, dict], idx: "Index") -> None:
    """Validate semantic conditions and evaluation results."""
    conditions: dict[str, tuple[dict, Path]] = {}
    for path, doc in docs.items():
        if doc.get("record_type") != "semantic_condition":
            continue
        cid = doc["condition_id"]
        if cid in conditions:
            err(f"semantics: {rel(path)}: duplicate condition_id '{cid}' "
                f"(also in {rel(conditions[cid][1])})")
        conditions[cid] = (doc, path)

        if doc["question_id"] not in idx.ids["question"]:
            err(f"semantics: {rel(path)}: unknown question '{doc['question_id']}'")
        if doc["indicates_finding"] not in idx.ids["finding"]:
            err(f"semantics: {rel(path)}: unknown finding '{doc['indicates_finding']}'")

        seen: set[str] = set()
        required = 0
        for el in doc["expected_elements"]:
            if el["element_id"] in seen:
                err(f"semantics: {rel(path)}: duplicate element_id '{el['element_id']}'")
            seen.add(el["element_id"])
            required += bool(el["required"])
            if CODE_LIKE.search(el["description"]):
                err(f"semantics: {rel(path)}: element {el['element_id']} description looks executable")
        if CODE_LIKE.search(doc["source_condition"]):
            err(f"semantics: {rel(path)}: source_condition looks executable")
        if required == 0:
            err(f"semantics: {rel(path)}: no expected_element is required, so the condition can never fire")

    for path, doc in docs.items():
        if doc.get("record_type") != "semantic_evaluation_result":
            continue
        blob = json.dumps(doc).upper()
        for bad in PROHIBITED_VERDICTS:
            if bad in blob:
                err(f"semantics: {rel(path)}: result carries prohibited verdict '{bad}'")
        cid = doc["condition_id"]
        entry = conditions.get(cid)
        if entry is None:
            err(f"semantics: {rel(path)}: unknown condition '{cid}'")
            continue
        cond = entry[0]
        if doc["question_id"] != cond["question_id"]:
            err(f"semantics: {rel(path)}: question '{doc['question_id']}' does not match "
                f"{cid} question '{cond['question_id']}'")
        valid = {el["element_id"] for el in cond["expected_elements"]}
        present, missing = set(doc["present_elements"]), set(doc["missing_elements"])
        for e in sorted(present - valid):
            err(f"semantics: {rel(path)}: present_elements references unknown element '{e}' for {cid}")
        for e in sorted(missing - valid):
            err(f"semantics: {rel(path)}: missing_elements references unknown element '{e}' for {cid}")
        for e in sorted(present & missing):
            err(f"semantics: {rel(path)}: element '{e}' is both present and missing")


def check_schemas(docs: dict[Path, dict], validators: dict[str, Draft7Validator]) -> None:
    schema_versions = {
        p.name: json.loads(p.read_text(encoding="utf-8")).get("x-driftguard-schema-version")
        for p in (ROOT / "schemas").glob("*.json")
    }
    for path, doc in docs.items():
        if "schemas" in path.parts:
            continue
        rt = doc.get("record_type")
        schema_name = SCHEMA_FOR_RECORD_TYPE.get(rt)
        if schema_name is not None and "schema_version" in doc:
            expected = schema_versions.get(schema_name)
            if expected and doc["schema_version"] != expected:
                err(f"versioning: {rel(path)}: schema_version '{doc['schema_version']}' does not "
                    f"match {schema_name} version '{expected}'")
        if schema_name is None:
            # Framework structural files are not schema-governed in this phase.
            if path.parent.name != "framework":
                warn(f"schema: {rel(path)}: record_type '{rt}' has no schema binding")
            continue
        validator = validators[schema_name]
        for e in sorted(validator.iter_errors(doc), key=lambda x: list(x.path)):
            loc = "/".join(str(p) for p in e.path) or "<root>"
            err(f"schema: {rel(path)}: {loc}: {e.message}")


# ------------------------------------------------------- 4/5. identity & refs
ID_PATTERNS = {
    "control": r"^SOC2-[A-Z]{1,2}[0-9]\.[0-9]+-[0-9]{3}$",
    "evidence": r"^EV-[A-Z0-9]+-[0-9]{3}$",
    "policy": r"^POL-[A-Z0-9]+-[0-9]{3}$",
    "questionnaire": r"^QN-[A-Z0-9]+-[0-9]{3}$",
    "question": r"^QN-[A-Z0-9]+-[0-9]{3}-Q[0-9]{2}$",
    "finding": r"^FND-[A-Z0-9]+-[0-9]{3}$",
    "remediation": r"^REM-[A-Z0-9]+-[0-9]{3}$",
    "mapping": r"^MAP-[0-9]{4}$",
    "source": r"^SRC-[A-Z0-9.-]+$",
}

SOURCE_TOKEN = re.compile(r"\bSRC-[A-Z0-9.-]+\b")

# ------------------------------------------------- gap signal condition grammar
GAP_GRAMMAR_VERSION = "1.0.0"
ENUMERATED_ANSWER_TYPES = {"single_select", "multi_select"}
# operator -> (required field, operand key)
GAP_OPERATORS = {
    "equals": ("answer.value", "value"),
    "in": ("answer.value", "values"),
    "not_includes_all": ("answer.values", "values"),
}
GAP_FIELDS = {"answer.value", "answer.values"}
CODE_LIKE = re.compile(r"(\beval\b|\bexec\b|=>|\$\{|<script|\bfunction\s*\(|\blambda\b|`|;\s*\w+\s*\()", re.I)


def gap_signal_expr_errors(expr, options: list[str], answer_type: str) -> list[str]:
    """Validate one condition_expr. Pure: returns error strings, never raises."""
    e: list[str] = []
    if not isinstance(expr, dict):
        return ["condition_expr must be an object"]
    if answer_type not in ENUMERATED_ANSWER_TYPES:
        e.append(f"condition_expr not permitted for answer_type '{answer_type}'")
    op, field = expr.get("operator"), expr.get("field")
    if op not in GAP_OPERATORS:
        return e + [f"unsupported operator '{op}'"]
    want_field, operand_key = GAP_OPERATORS[op]
    if field not in GAP_FIELDS:
        e.append(f"unsupported field '{field}'")
    elif field != want_field:
        e.append(f"operator '{op}' requires field '{want_field}', got '{field}'")
    if field == "answer.values" and answer_type != "multi_select":
        e.append("field 'answer.values' requires a multi_select question")
    for extra in set(expr) - {"operator", "field", "value", "values"}:
        e.append(f"unexpected property '{extra}'")
    other = "values" if operand_key == "value" else "value"
    if other in expr:
        e.append(f"operator '{op}' must not carry '{other}'")
    if operand_key not in expr:
        return e + [f"operator '{op}' requires '{operand_key}'"]
    operand = expr[operand_key]
    if operand_key == "value":
        items = [operand] if isinstance(operand, str) else None
        if items is None:
            return e + ["'value' must be a string"]
    else:
        if not isinstance(operand, list) or not operand or not all(isinstance(i, str) for i in operand):
            return e + ["'values' must be a non-empty array of strings"]
        if len(set(operand)) != len(operand):
            e.append("'values' contains duplicates")
        items = operand
    for v in items:
        if CODE_LIKE.search(v):
            e.append(f"operand looks executable and is rejected: {v!r}")
        elif v not in options:
            e.append(f"operand {v!r} is not one of the question's declared options")
    return e


def check_gap_signals(docs: dict[Path, dict]) -> None:
    for path, doc in docs.items():
        if doc.get("record_type") != "questionnaire":
            continue
        if doc.get("gap_signal_grammar_version") != GAP_GRAMMAR_VERSION:
            err(f"grammar: {rel(path)}: gap_signal_grammar_version "
                f"'{doc.get('gap_signal_grammar_version')}' != {GAP_GRAMMAR_VERSION}")
        for q in doc.get("questions", []):
            qid, atype = q["question_id"], q["answer_type"]
            options = q.get("options", [])
            for i, g in enumerate(q.get("gap_signals", [])):
                expr = g.get("condition_expr")
                if expr is None:
                    if atype in ENUMERATED_ANSWER_TYPES:
                        err(f"grammar: {rel(path)}: {qid}.gap_signals[{i}] has an enumerated "
                            f"answer_type but no condition_expr")
                    continue
                for m in gap_signal_expr_errors(expr, options, atype):
                    err(f"grammar: {rel(path)}: {qid}.gap_signals[{i}]: {m}")


class Index:
    def __init__(self) -> None:
        self.ids: dict[str, set[str]] = defaultdict(set)
        self.names: dict[str, dict[str, str]] = defaultdict(dict)
        self.home: dict[str, Path] = {}

    def add(self, kind: str, _id: str, path: Path, name: str | None = None) -> None:
        if _id in self.ids[kind]:
            err(f"identity: duplicate {kind} id '{_id}' (also in {rel(self.home[_id])})")
        pattern = ID_PATTERNS.get(kind)
        if pattern and not re.match(pattern, _id):
            err(f"identity: {rel(path)}: {kind} id '{_id}' does not match convention {pattern}")
        self.ids[kind].add(_id)
        self.home[_id] = path
        if name:
            existing = self.names[kind].get(name.lower())
            if existing and existing != _id:
                err(f"duplicate-concept: {kind} name '{name}' used by both {existing} and {_id}")
            self.names[kind][name.lower()] = _id


def build_index(docs: dict[Path, dict]) -> tuple[Index, set[str], dict]:
    idx = Index()
    criteria: set[str] = set()

    tsc_path = ROOT / "framework" / "trust_services_criteria.json"
    tsc = docs.get(tsc_path)
    if tsc is None:
        err("index: framework/trust_services_criteria.json missing; criterion refs cannot be checked")
    else:
        for series in tsc.get("criteria_series", []):
            criteria.update(series.get("criteria", []))
        declared = tsc.get("counts", {}).get("total_criteria")
        if declared is not None and declared != len(criteria):
            err(f"counts: trust_services_criteria.json declares {declared} total criteria "
                f"but enumerates {len(criteria)}")

    registry = docs.get(ROOT / "framework" / "references.json", {})
    for s in registry.get("sources", []):
        idx.add("source", s["source_id"], ROOT / "framework" / "references.json", s.get("title"))

    for path, doc in docs.items():
        rt = doc.get("record_type")
        if rt == "control":
            idx.add("control", doc["control_id"], path, doc.get("control_name"))
        elif rt == "evidence":
            idx.add("evidence", doc["evidence_id"], path, doc.get("name"))
        elif rt == "policy":
            idx.add("policy", doc["policy_id"], path, doc.get("name"))
        elif rt == "finding":
            idx.add("finding", doc["finding_id"], path, doc.get("name"))
        elif rt == "remediation":
            idx.add("remediation", doc["remediation_id"], path, doc.get("name"))
        elif rt == "questionnaire":
            idx.add("questionnaire", doc["questionnaire_id"], path, doc.get("name"))
            for q in doc.get("questions", []):
                idx.add("question", q["question_id"], path)
        elif rt == "mapping_set":
            for m in doc.get("mappings", []):
                idx.add("mapping", m["mapping_id"], path)
    return idx, criteria, registry


def ref(idx: Index, criteria: set[str], kind: str, value: str, path: Path, field: str) -> None:
    pool = criteria if kind == "criterion" else idx.ids.get(kind, set())
    if value not in pool:
        err(f"reference: {rel(path)}: {field} -> unknown {kind} '{value}'")


def check_references(docs: dict[Path, dict], idx: Index, criteria: set[str]) -> None:
    for path, doc in docs.items():
        rt = doc.get("record_type")
        if rt == "source_registry":
            continue  # its 'sources' key is the registry itself, not citations

        for sid in doc.get("sources", []):
            ref(idx, criteria, "source", sid, path, "sources")
        for sr in doc.get("source_refs", []):
            ref(idx, criteria, "source", sr["source_id"], path, "source_refs")
        if rt in SCHEMA_FOR_RECORD_TYPE and rt not in UNSOURCED_RECORD_TYPES:
            if not doc.get("sources"):
                err(f"sourcing: {rel(path)}: record carries no sources")

        if rt == "control":
            ref(idx, criteria, "criterion", doc["criterion"], path, "criterion")
            for c in doc.get("secondary_criteria", []):
                ref(idx, criteria, "criterion", c, path, "secondary_criteria")
            for e in doc.get("evidence_examples", []):
                ref(idx, criteria, "evidence", e["evidence_id"], path, "evidence_examples")
            for p in doc.get("policy_examples", []):
                ref(idx, criteria, "policy", p, path, "policy_examples")
            for f in doc.get("common_findings", []):
                ref(idx, criteria, "finding", f, path, "common_findings")
            for r in doc.get("remediation", []):
                ref(idx, criteria, "remediation", r, path, "remediation")
            for q in doc.get("questionnaire_questions", []):
                ref(idx, criteria, "question", q, path, "questionnaire_questions")
            for rc in doc.get("related_controls", []):
                ref(idx, criteria, "control", rc["control_id"], path, "related_controls")
            for m in doc.get("mappings", []):
                ref(idx, criteria, "source", m["source_id"], path, "mappings.source_id")

        elif rt == "evidence":
            for c in doc.get("applicable_controls", []):
                ref(idx, criteria, "control", c["control_id"], path, "applicable_controls")
            for c in doc.get("applicable_criteria", []):
                ref(idx, criteria, "criterion", c, path, "applicable_criteria")
            for e in doc.get("type2_pairing_requirement", []):
                ref(idx, criteria, "evidence", e, path, "type2_pairing_requirement")
            for vr in doc.get("validation_rules", []):
                if "failure_finding" in vr:
                    ref(idx, criteria, "finding", vr["failure_finding"], path,
                        f"validation_rules[{vr['rule_id']}].failure_finding")
            for ci in doc.get("common_issues", []):
                if "related_finding" in ci:
                    ref(idx, criteria, "finding", ci["related_finding"], path, "common_issues.related_finding")

        elif rt == "policy":
            for c in doc.get("supported_controls", []):
                ref(idx, criteria, "control", c, path, "supported_controls")
            for c in doc.get("supported_criteria", []):
                ref(idx, criteria, "criterion", c, path, "supported_criteria")
            for e in doc.get("evidence_examples", []):
                ref(idx, criteria, "evidence", e, path, "evidence_examples")
            for f in doc.get("common_findings", []):
                ref(idx, criteria, "finding", f, path, "common_findings")
            for p in doc.get("related_policies", []):
                ref(idx, criteria, "policy", p, path, "related_policies")
            for e in doc.get("approval_expectation", {}).get("evidence_of_approval", []):
                ref(idx, criteria, "evidence", e, path, "approval_expectation.evidence_of_approval")
            for el in doc.get("required_elements", []):
                for sid in el.get("sources", []):
                    ref(idx, criteria, "source", sid, path, f"required_elements[{el['element_id']}].sources")

        elif rt == "questionnaire":
            for c in doc.get("covers_criteria", []):
                ref(idx, criteria, "criterion", c, path, "covers_criteria")
            for q in doc.get("questions", []):
                qid = q["question_id"]
                if not qid.startswith(doc["questionnaire_id"] + "-Q"):
                    err(f"identity: {rel(path)}: question '{qid}' not namespaced under "
                        f"{doc['questionnaire_id']}")
                for c in q.get("related_controls", []):
                    ref(idx, criteria, "control", c, path, f"{qid}.related_controls")
                for c in q.get("related_criteria", []):
                    ref(idx, criteria, "criterion", c, path, f"{qid}.related_criteria")
                for e in q.get("expected_evidence", []):
                    ref(idx, criteria, "evidence", e, path, f"{qid}.expected_evidence")
                for g in q.get("gap_signals", []):
                    ref(idx, criteria, "finding", g["indicates_finding"], path, f"{qid}.gap_signals")
                for fu in q.get("follow_up_if", []):
                    ref(idx, criteria, "question", fu["question_id"], path, f"{qid}.follow_up_if")

        elif rt == "finding":
            for c in doc.get("affected_criteria", []):
                ref(idx, criteria, "criterion", c, path, "affected_criteria")
            for c in doc.get("affected_controls", []):
                ref(idx, criteria, "control", c, path, "affected_controls")
            for c in doc.get("severity_factors", {}).get("compensating_controls", []):
                ref(idx, criteria, "control", c, path, "severity_factors.compensating_controls")
            for r in doc.get("remediations", []):
                ref(idx, criteria, "remediation", r, path, "remediations")
            for s in doc.get("detection_signals", []):
                for e in s.get("related_evidence", []):
                    ref(idx, criteria, "evidence", e, path, f"detection_signals[{s['signal_id']}]")
                if "related_question" in s:
                    ref(idx, criteria, "question", s["related_question"], path,
                        f"detection_signals[{s['signal_id']}]")

        elif rt == "remediation":
            for f in doc.get("addresses_findings", []):
                ref(idx, criteria, "finding", f, path, "addresses_findings")
            for c in doc.get("strengthens_controls", []):
                ref(idx, criteria, "control", c, path, "strengthens_controls")
            for c in doc.get("affected_criteria", []):
                ref(idx, criteria, "criterion", c, path, "affected_criteria")
            for s in doc.get("steps", []):
                for e in s.get("produces_evidence", []):
                    ref(idx, criteria, "evidence", e, path, f"steps[{s['step']}].produces_evidence")
            for e in doc.get("verification_method", {}).get("verifying_evidence", []):
                ref(idx, criteria, "evidence", e, path, "verification_method.verifying_evidence")
            for r in doc.get("paired_remediations", []):
                ref(idx, criteria, "remediation", r, path, "paired_remediations")


# ---------------------------------------------------------------- 6. mappings
ENTITY_KIND = {
    "control": "control", "evidence": "evidence", "policy": "policy",
    "questionnaire": "questionnaire", "question": "question",
    "finding": "finding", "remediation": "remediation",
    "criterion": "criterion", "source": "source",
}


def check_mappings(docs: dict[Path, dict], idx: Index, criteria: set[str]) -> None:
    edges: set[tuple[str, str, str]] = set()

    # The relationship vocabulary is global, not per-file: a mapping set may use any
    # type declared in any set. Identically-named types must carry identical
    # definitions, otherwise the vocabulary has forked.
    declared: set[str] = set()
    definitions: dict[str, tuple[dict, Path]] = {}
    for path, doc in docs.items():
        if doc.get("record_type") != "mapping_set":
            continue
        for r in doc.get("relationship_types", []):
            declared.add(r["type"])
            prior = definitions.get(r["type"])
            if prior and prior[0] != r:
                err(f"mapping: {rel(path)}: relationship type '{r['type']}' is defined "
                    f"differently here than in {rel(prior[1])}")
            definitions.setdefault(r["type"], (r, path))

    for path, doc in docs.items():
        if doc.get("record_type") != "mapping_set":
            continue
        inverses = {r["inverse"] for r in doc.get("relationship_types", [])}
        overlap = {r["type"] for r in doc.get("relationship_types", [])} & inverses
        if overlap:
            err(f"mapping: {rel(path)}: relationship type(s) also declared as an inverse: {sorted(overlap)}")
        for m in doc.get("mappings", []):
            mid = m["mapping_id"]
            if m["relationship"] not in declared:
                err(f"mapping: {rel(path)}: {mid} uses undeclared relationship '{m['relationship']}'")
            for side in ("from", "to"):
                kind = ENTITY_KIND[m[side]["entity_type"]]
                ref(idx, criteria, kind, m[side]["id"], path, f"{mid}.{side}")
            for sid in m.get("sources", []):
                ref(idx, criteria, "source", sid, path, f"{mid}.sources")
            edges.add((m["from"]["id"], m["relationship"], m["to"]["id"]))

    # Convenience references on entity records must be present in the graph.
    def expect(a: str, r: str, b: str, path: Path, field: str) -> None:
        if (a, r, b) not in edges:
            warn(f"graph-consistency: {rel(path)}: {field} {a} -> {b} not present as "
                 f"'{r}' in any mapping set")

    for path, doc in docs.items():
        rt = doc.get("record_type")
        if rt == "control":
            cid = doc["control_id"]
            expect(cid, "addresses_criterion", doc["criterion"], path, "criterion")
            for e in doc.get("evidence_examples", []):
                expect(cid, "supported_by_evidence", e["evidence_id"], path, "evidence_examples")
            for p in doc.get("policy_examples", []):
                expect(cid, "documented_by_policy", p, path, "policy_examples")
            for q in doc.get("questionnaire_questions", []):
                expect(cid, "assessed_by_question", q, path, "questionnaire_questions")
        elif rt == "finding":
            fid = doc["finding_id"]
            for r in doc.get("remediations", []):
                expect(fid, "remediated_by", r, path, "remediations")
            for c in doc.get("affected_controls", []):
                expect(fid, "finding_affects_control", c, path, "affected_controls")
        elif rt == "evidence":
            eid = doc["evidence_id"]
            for c in doc.get("applicable_controls", []):
                expect(c["control_id"], "supported_by_evidence", eid, path, "applicable_controls")
        elif rt == "remediation":
            rid = doc["remediation_id"]
            for e in doc.get("verification_method", {}).get("verifying_evidence", []):
                expect(rid, "verified_by_evidence", e, path, "verification_method")


# ----------------------------------------------------------------- 7. sources
def check_source_usage(docs: dict[Path, dict], idx: Index, registry: dict) -> None:
    tiers = {t["tier"]: t["key"] for t in registry.get("authority_tiers", [])}
    by_id = {s["source_id"]: s for s in registry.get("sources", [])}
    for s in registry.get("sources", []):
        if tiers.get(s["authority_tier"]) != s["authority_key"]:
            err(f"sourcing: references.json: {s['source_id']} tier {s['authority_tier']} "
                f"does not match authority_key '{s['authority_key']}'")
    for doc in docs.values():
        for sr in doc.get("source_refs", []):
            declared = by_id.get(sr["source_id"], {}).get("authority_tier")
            if declared is not None and sr.get("authority_tier") != declared:
                err(f"sourcing: source_ref cites {sr['source_id']} at tier "
                    f"{sr.get('authority_tier')} but the registry declares tier {declared}")

    # Textual sweep: every SRC- token anywhere in the knowledge base, including
    # Markdown inline citations and front matter, must resolve to the registry.
    used: set[str] = set()
    registry_file = ROOT / "framework" / "references.json"
    for path in sorted(list(ROOT.rglob("*.json")) + list(ROOT.rglob("*.md"))):
        tokens = set(SOURCE_TOKEN.findall(path.read_text(encoding="utf-8")))
        for tok in sorted(tokens):
            if tok not in idx.ids["source"]:
                err(f"sourcing: {rel(path)}: cites unregistered source '{tok}'")
        if path != registry_file:
            used.update(tokens)
    for sid in sorted(idx.ids["source"] - used):
        warn(f"sourcing: registered source '{sid}' is not cited by any record yet")


def main() -> int:
    check_structure()
    docs = load_all_json()
    if ERRORS:
        report()
        return 1
    validators = build_validators()
    check_schemas(docs, validators)
    idx, criteria, registry = build_index(docs)
    check_references(docs, idx, criteria)
    check_gap_signals(docs)
    check_semantics(docs, idx)
    check_mappings(docs, idx, criteria)
    check_source_usage(docs, idx, registry)

    print(f"scanned {len(docs)} JSON files")
    print(f"indexed: {len(idx.ids['control'])} controls, {len(idx.ids['evidence'])} evidence, "
          f"{len(idx.ids['policy'])} policies, {len(idx.ids['questionnaire'])} questionnaires "
          f"({len(idx.ids['question'])} questions), {len(idx.ids['finding'])} findings, "
          f"{len(idx.ids['remediation'])} remediations, {len(idx.ids['mapping'])} mappings, "
          f"{len(idx.ids['source'])} sources, {len(criteria)} criteria")
    return report()


def report() -> int:
    for w in WARNINGS:
        print(f"WARN  {w}")
    for e in ERRORS:
        print(f"ERROR {e}")
    print(f"\n{len(ERRORS)} error(s), {len(WARNINGS)} warning(s)")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
