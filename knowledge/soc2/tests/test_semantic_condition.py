#!/usr/bin/env python3
"""Tests for the semantic condition and semantic evaluation result schemas.

Schema-level validation only. Nothing here evaluates a condition, and no
evaluator is exercised.

Run:  python3 knowledge/soc2/tests/test_semantic_condition.py
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from validate import PROHIBITED_VERDICTS, build_validators  # noqa: E402

V = build_validators()
COND = V["semantic_condition.schema.json"]
RES = V["semantic_evaluation_result.schema.json"]

QUESTIONS = {
    q["question_id"]
    for p in (ROOT / "questionnaires").glob("*.json")
    for q in json.loads(p.read_text())["questions"]
}

BASE_COND = json.loads((ROOT / "semantics" / "SEMCOND-0001.json").read_text())
BASE_RES = json.loads((ROOT / "semantics" / "SEMRES-EXAMPLE-0001.json").read_text())
COND_ELEMENTS = {e["element_id"] for e in BASE_COND["expected_elements"]}


def cond(**over):
    d = copy.deepcopy(BASE_COND)
    d.update(over)
    return d


def res(**over):
    d = copy.deepcopy(BASE_RES)
    d.update(over)
    return d


def cond_errors(d) -> list[str]:
    """Schema errors plus the cross-record checks the validator performs."""
    e = [x.message for x in COND.iter_errors(d)]
    if d.get("question_id") not in QUESTIONS:
        e.append("unknown question reference")
    ids = [x["element_id"] for x in d.get("expected_elements", [])]
    if len(ids) != len(set(ids)):
        e.append("duplicate element_id")
    if d.get("expected_elements") and not any(x["required"] for x in d["expected_elements"]):
        e.append("no required element")
    return e


def res_errors(d, elements=COND_ELEMENTS) -> list[str]:
    e = [x.message for x in RES.iter_errors(d)]
    present, missing = set(d.get("present_elements", [])), set(d.get("missing_elements", []))
    for x in sorted(present - elements):
        e.append(f"unknown present element {x}")
    for x in sorted(missing - elements):
        e.append(f"unknown missing element {x}")
    for x in sorted(present & missing):
        e.append(f"element {x} both present and missing")
    blob = json.dumps(d).upper()
    for bad in PROHIBITED_VERDICTS:
        if bad in blob:
            e.append(f"prohibited verdict {bad}")
    return e


CASES: list[tuple[str, list[str], bool]] = [
    ("valid semantic condition", cond_errors(cond()), True),
    ("valid evaluation result", res_errors(res()), True),

    ("invalid question reference",
     cond_errors(cond(question_id="QN-NOPE-001-Q01")), False),
    ("duplicate element ID",
     cond_errors(cond(expected_elements=[
         {"element_id": "SE-001", "description": "first element", "required": True},
         {"element_id": "SE-001", "description": "same id again", "required": True}])), False),
    ("condition with no required element can never fire",
     cond_errors(cond(expected_elements=[
         {"element_id": "SE-001", "description": "optional only", "required": False}])), False),
    ("condition rejects an unknown evaluation_type",
     cond_errors(cond(evaluation_type="deterministic")), False),
    ("condition rejects an unexpected property",
     cond_errors(cond(expression="answer.contains('backup')")), False),

    ("invalid assessment", res_errors(res(assessment="NON_COMPLIANT")), False),
    ("prohibited verdict anywhere in the record",
     res_errors(res(notes=["the entity is SOC2_FAILED"])), False),
    ("confidence above 1", res_errors(res(confidence=1.4)), False),
    ("confidence below 0", res_errors(res(confidence=-0.1)), False),
    ("confidence not numeric", res_errors(res(confidence="high")), False),
    ("unknown present element",
     res_errors(res(present_elements=["SE-999"], missing_elements=[])), False),
    ("unknown missing element",
     res_errors(res(present_elements=[], missing_elements=["SE-404"])), False),
    ("element both present and missing",
     res_errors(res(present_elements=["SE-001"], missing_elements=["SE-001"])), False),
    ("unknown reason code", res_errors(res(reason_codes=["vibes"])), False),
    ("empty reason codes", res_errors(res(reason_codes=[])), False),
]


def main() -> int:
    failed = 0
    for name, errors, expect_valid in CASES:
        got_valid = not errors
        if got_valid != expect_valid:
            print(f"  FAIL  {name}: expected {'valid' if expect_valid else 'invalid'}, "
                  f"got {errors or 'valid'}")
            failed += 1
        else:
            print(f"  ok    {name}")

    corpus = 0
    for p in (ROOT / "semantics").glob("*.json"):
        d = json.loads(p.read_text())
        errs = cond_errors(d) if d["record_type"] == "semantic_condition" else res_errors(
            d, {e["element_id"] for e in json.loads(
                (ROOT / "semantics" / f"{d['condition_id']}.json").read_text())["expected_elements"]})
        if errs:
            print(f"  FAIL  corpus {p.name}: {errs}")
            failed += 1
        corpus += 1
    print(f"  ok    {corpus} semantics records in the corpus validate")
    print(f"\n{'FAILED' if failed else 'PASSED'}: {failed} failure(s)")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
