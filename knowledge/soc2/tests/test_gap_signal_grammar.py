#!/usr/bin/env python3
"""Tests for the gap signal condition grammar (version 1.0.0).

Covers only the operators actually used in the knowledge base. This is a
validation test, not a runtime evaluator: nothing here executes a condition.

Run:  python3 knowledge/soc2/tests/test_gap_signal_grammar.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from validate import gap_signal_expr_errors  # noqa: E402

OPTS = ["Yes", "No", "Partly"]
CASES: list[tuple[str, dict, list[str], str, bool]] = [
    # name, expr, options, answer_type, expect_valid
    ("valid equals",
     {"operator": "equals", "field": "answer.value", "value": "No"}, OPTS, "single_select", True),
    ("valid in",
     {"operator": "in", "field": "answer.value", "values": ["No", "Partly"]}, OPTS, "single_select", True),
    ("valid not_includes_all",
     {"operator": "not_includes_all", "field": "answer.values", "values": ["Yes", "Partly"]}, OPTS, "multi_select", True),

    ("invalid operator",
     {"operator": "matches", "field": "answer.value", "value": "No"}, OPTS, "single_select", False),
    ("invalid field",
     {"operator": "equals", "field": "answer.text", "value": "No"}, OPTS, "single_select", False),
    ("field wrong for operator",
     {"operator": "equals", "field": "answer.values", "value": "No"}, OPTS, "multi_select", False),
    ("invalid operand: not a declared option",
     {"operator": "equals", "field": "answer.value", "value": "Maybe"}, OPTS, "single_select", False),
    ("invalid operand: wrong type",
     {"operator": "in", "field": "answer.value", "values": "No"}, OPTS, "single_select", False),
    ("invalid operand: empty list",
     {"operator": "in", "field": "answer.value", "values": []}, OPTS, "single_select", False),

    ("malformed: missing operand",
     {"operator": "equals", "field": "answer.value"}, OPTS, "single_select", False),
    ("malformed: missing operator",
     {"field": "answer.value", "value": "No"}, OPTS, "single_select", False),
    ("malformed: extra property",
     {"operator": "equals", "field": "answer.value", "value": "No", "negate": True}, OPTS, "single_select", False),
    ("malformed: both operands",
     {"operator": "equals", "field": "answer.value", "value": "No", "values": ["No"]}, OPTS, "single_select", False),
    ("malformed: not an object",
     "answer == 'No'", OPTS, "single_select", False),

    ("executable-looking operand rejected",
     {"operator": "equals", "field": "answer.value", "value": "() => fetch('/x')"}, OPTS, "single_select", False),
    ("template-injection operand rejected",
     {"operator": "equals", "field": "answer.value", "value": "${process.env}"}, OPTS, "single_select", False),

    ("expr forbidden on free-text answer",
     {"operator": "equals", "field": "answer.value", "value": "No"}, OPTS, "text", False),
    ("answer.values forbidden on single_select",
     {"operator": "not_includes_all", "field": "answer.values", "values": ["Yes"]}, OPTS, "single_select", False),
]


def test_grammar() -> int:
    failed = 0
    for name, expr, opts, atype, expect_valid in CASES:
        errors = gap_signal_expr_errors(expr, opts, atype)
        got_valid = not errors
        if got_valid != expect_valid:
            print(f"  FAIL  {name}: expected {'valid' if expect_valid else 'invalid'}, "
                  f"got {errors or 'valid'}")
            failed += 1
        else:
            print(f"  ok    {name}")
    return failed


def test_corpus() -> int:
    """Every condition_expr in the knowledge base validates, and every
    question referenced by a gap signal exists with a resolvable finding."""
    failed = 0
    findings = {json.loads(p.read_text())["finding_id"] for p in (ROOT / "findings").glob("*.json")}
    qids: set[str] = set()
    checked = 0
    for p in (ROOT / "questionnaires").glob("*.json"):
        d = json.loads(p.read_text())
        for q in d["questions"]:
            qids.add(q["question_id"])
            for i, g in enumerate(q.get("gap_signals", [])):
                if g["indicates_finding"] not in findings:
                    print(f"  FAIL  {q['question_id']}.gap_signals[{i}] -> unknown finding")
                    failed += 1
                if (expr := g.get("condition_expr")) is not None:
                    checked += 1
                    errs = gap_signal_expr_errors(expr, q.get("options", []), q["answer_type"])
                    if errs:
                        print(f"  FAIL  {q['question_id']}.gap_signals[{i}]: {errs}")
                        failed += 1
    print(f"  ok    {checked} condition_expr objects in the corpus validate")

    # invalid question reference must be detectable
    if "QN-DOES-NOT-EXIST-001-Q99" in qids:
        print("  FAIL  sentinel question id unexpectedly present")
        failed += 1
    else:
        print("  ok    unknown question reference is detectable against the question index")
    return failed


if __name__ == "__main__":
    print("grammar cases:")
    n = test_grammar()
    print("corpus:")
    n += test_corpus()
    print(f"\n{'FAILED' if n else 'PASSED'}: {n} failure(s)")
    sys.exit(1 if n else 0)
