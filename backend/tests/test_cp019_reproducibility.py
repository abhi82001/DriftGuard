#!/usr/bin/env python3
"""CP019 step 4: reproducibility, run stamp and AI-path safeguards.

Uses a small synthetic pack. Set DRIFTGUARD_PACK_DIR to a folder to also run the
double-run check on a real (uncommitted) pack.
"""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

import app as webapp  # noqa: E402
from claims import SecurityClaim  # noqa: E402
from documents import PARTIAL, DocumentAnalyzer, is_ai_derived  # noqa: E402
from evaluation.execution import SemanticEvaluationRunner, ai_provenance  # noqa: E402
from evidence.reproducibility import canonical_result, input_hash, knowledge_hash, run_stamp  # noqa: E402
from ingestion import Chunk, Document  # noqa: E402

AS_OF = date(2026, 10, 8)
PACK = [
    ("Access_Control_Policy.txt", b"Access Control Policy\n\nMulti-factor authentication is required for all employees and administrators "
     b"accessing production systems.\n\nUser access reviews are required quarterly and include employees, contractors.\n\n"
     b"Access is revoked within 24 hours of termination.\n"),
    ("Vendor SOC 2 Type II Report (04-01-2025 to 3-31-2026).txt", b"Report. Multi-factor authentication is enforced for production domains. "
     b"Privileged access is time-bound through just-in-time elevation.\n"),
    ("Azure Privacy Impact Assessment.txt", b"Privacy assessment. Multi-factor authentication is required for administrators of production systems.\n"),
    ("users.csv", b"user,role,mfa_enabled\nalice,admin,true\nbob,user,false\n"),
]
GRAPH = SRC.parent


def _canon(payloads, as_of=AS_OF):
    return canonical_result(webapp.analyze_payloads("vendor", payloads, assessment_date=as_of))


def _dump(obj):
    return json.dumps(obj, sort_keys=True, default=str)


def test_same_inputs_give_identical_canonical_output_twice():
    a, b = _canon(PACK), _canon(PACK)
    assert _dump(a) == _dump(b)
    assert "assessment_id" not in _dump(a)


def test_upload_order_does_not_change_canonical_output():
    assert _dump(_canon(PACK)) == _dump(_canon(list(reversed(PACK))))


def test_different_hash_seeds_give_identical_output():
    code = ("import sys, json, os; sys.path.insert(0, %r); os.environ['DRIFTGUARD_DEMO_MODE']='1'; "
            "from datetime import date; import app; from evidence.reproducibility import canonical_result as c; "
            "import test_cp019_reproducibility as t; "
            "print(json.dumps(c(app.analyze_payloads('vendor', t.PACK, assessment_date=date(2026,10,8))), sort_keys=True, default=str))"
            ) % str(SRC)
    outs = []
    for seed in ("1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(Path(__file__).parent))
        outs.append(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=300).stdout)
    assert outs[0].strip() and outs[0] == outs[1]


@pytest.mark.skipif(not os.getenv("DRIFTGUARD_PACK_DIR"), reason="real pack not supplied")
def test_real_pack_twice_identical():
    root = Path(os.environ["DRIFTGUARD_PACK_DIR"])
    files = [(p.name, p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in webapp.SUPPORTED]
    assert _dump(_canon(files)) == _dump(_canon(files))


def test_run_stamp_records_input_hash_versions_and_assessment_date():
    r = webapp.analyze_payloads("vendor", PACK, assessment_date=AS_OF)
    s = r.run_stamp
    assert s["input_hash"] == input_hash(reversed(PACK)) and len(s["input_hash"]) == 64
    assert s["assessment_date"] == "2026-10-08" and s["assessment_date_source"] == "supplied"
    assert s["engine_version"] and s["grammar_version"] == "1.0.0" and s["knowledge_hash"] == knowledge_hash()
    assert s["authority_rules_version"] and s["ai_status"] == r.semantic_status
    changed = list(PACK) + [("extra.txt", b"more text")]
    assert input_hash(changed) != s["input_hash"]


def test_ai_disabled_by_default_and_output_unaffected():
    r = webapp.analyze_payloads("vendor", PACK, assessment_date=AS_OF)
    assert r.semantic_status != "SEMANTIC_ACTIVE"
    assert not any(is_ai_derived(c) for c in r.claims)
    assert all(not f.ai_derived for a in r.areas for f in a.known_facts)


def _q01_with(claims):
    name = "Vendor policy.txt"

    class Fixed:
        def extract(self, _):
            return claims
    res = DocumentAnalyzer(webapp.ANALYZER.knowledge, extractor=Fixed()).analyze(
        "v", [Document(name, "policy", (Chunk(name, "line 1", "x"),))], [], True, assessment_date=AS_OF)
    return next(a for a in res.areas if a.question_id == "QN-ACCESS-001-Q01")


def _claim(attr, value, nature, method):
    return SecurityClaim("mfa", "Multi-factor authentication statement for production systems", "Vendor policy.txt",
                         f"line {attr}", "Multi-factor authentication statement for production systems", nature,
                         {attr: value}, extraction_method=method)


def test_model_derived_facts_alone_cannot_establish_and_are_marked_with_source_ids():
    ai = "semantic-grounded-v1"
    area = _q01_with([_claim("requirement", "required", "POLICY", ai), _claim("scope", ["production systems"], "POLICY", ai),
                      _claim("enforcement_evidence", True, "CONFIGURATION", ai)])
    assert area.status == PARTIAL
    assert area.known_facts and all(f.ai_derived and f.source_ids for f in area.known_facts)
    assert any("human confirmation" in m for m in area.missing_facts)


def test_deterministic_facts_still_establish_and_model_cannot_flip_them():
    det = "deterministic-grounded-v1"
    base = [_claim("requirement", "required", "POLICY", det), _claim("scope", ["production systems"], "POLICY", det),
            _claim("enforcement_evidence", True, "CONFIGURATION", det)]
    assert _q01_with(base).status == "ESTABLISHED"
    # A model claim at another location that disagrees is surfaced, never silently decisive.
    contra = base + [_claim("scope", ["employees"], "POLICY", "semantic-grounded-v1")]
    area = _q01_with(contra)
    assert area.status == PARTIAL and any("differs from the deterministic value" in m for m in area.missing_facts)


def test_categorical_model_claim_cannot_create_a_conflict():
    mk = lambda v, m: SecurityClaim("privileged_access", "Privileged access model statement for production", "Vendor policy.txt",
                                    f"line {v}", "Privileged access model statement for production", "POLICY",
                                    {"privilege_model": v}, extraction_method=m)

    class Fixed:
        def extract(self, _):
            return [mk("standing", "deterministic-grounded-v1"), mk("time-bounded", "semantic-grounded-v1")]
    n = "Vendor policy.txt"
    res = DocumentAnalyzer(webapp.ANALYZER.knowledge, extractor=Fixed()).analyze(
        "v", [Document(n, "policy", (Chunk(n, "line 1", "x"),))], [], True, assessment_date=AS_OF)
    q08 = next(a for a in res.areas if a.question_id == "QN-ACCESS-001-Q08")
    assert q08.status != "CONFLICT" and not q08.conflict_details


def test_semantic_runner_marks_results_as_model_derived_with_source_ids():
    from evaluation.engine import EvaluationEngine
    from evaluation.semantic import SemanticEvaluationResult, SemanticVerdict
    from evaluation.semantic import build_semantic_request

    class Stub:
        def evaluate(self, request):
            return SemanticEvaluationResult("SEMRES-T", request.condition_id, request.question_id,
                                            SemanticVerdict.INSUFFICIENT.value, 0.5, (), tuple(e.element_id for e in request.expected_elements)[:1],
                                            ("element_not_mentioned",), True)
    engine = EvaluationEngine.from_repository()
    runner = SemanticEvaluationRunner(engine.knowledge, Stub())
    out = runner.run("QN-ACCESS-001", "QN-ACCESS-001-Q09", "We encrypt the primary database.")
    prov = runner.provenance[out.result_id]
    assert prov["ai_derived"] is True and prov["source_ids"] and prov["evaluator"] == "Stub"
    req = build_semantic_request(engine.knowledge, "QN-ACCESS-001", "QN-ACCESS-001-Q09", "x")
    assert ai_provenance(req, Stub())["source_ids"][0] == "QN-ACCESS-001-Q09#answer"
