#!/usr/bin/env python3
import os, sys
from pathlib import Path
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC)); sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"
from evidence.backbone import analyze_artifacts
from evidence.organization import build_organization_view
from fixtures import user_access_review_fixture as fx


def test_1_action_center_surfaces_unclassified_grounded_evidence():
    a = analyze_artifacts([("policy.txt", b"Multi-factor authentication is required for production systems.")])
    view = build_organization_view(a)
    assert view.observed_unclassified_count == 1
    assert any(x.kind == "CLASSIFICATION_REVIEW" for x in view.work_items)


def test_2_structured_review_exceptions_become_work_items():
    a = analyze_artifacts([(fx.REAL_FILENAME, fx.real_workbook())])
    view = build_organization_view(a)
    assert view.recognized_count == 1
    assert view.work_items
    assert any(x.kind in {"EVIDENCE_FOLLOW_UP", "ARTIFACT_REVIEW", "VALIDATION_EXCEPTION"} for x in view.work_items)


def test_3_reuse_index_finds_same_concept_across_files():
    a = analyze_artifacts([
        ("one.txt", b"Multi-factor authentication is required for production systems."),
        ("two.md", b"# Standard\nMulti-factor authentication is required for production systems."),
    ])
    view = build_organization_view(a)
    keys = {x.fact_key for x in view.reusable_concepts}
    assert "mfa.requirement" in keys


def test_4_policy_and_implementation_are_not_false_conflicts():
    a = analyze_artifacts([
        ("policy.txt", b"Multi-factor authentication is required for production systems."),
        ("config.txt", b"Multi-factor authentication is enforced for production systems."),
    ])
    view = build_organization_view(a)
    assert not view.variances


def test_5_same_nature_different_values_are_review_variance():
    # Use immutable backbone records directly to isolate portfolio comparison behavior.
    from evidence.backbone import EvidenceAnalysis, EvidenceArtifact, ArtifactFact
    def artifact(i, value):
        return EvidenceArtifact(i, f"{i}.txt", "txt", "other", "X", "", "OBSERVED", False,
            facts=(ArtifactFact("sample.count", "sample count", value, "STRUCTURED_RECORD", "stated"),))
    view = build_organization_view(EvidenceAnalysis((artifact("a", 10), artifact("b", 12))))
    assert len(view.variances) == 1
    assert any(x.kind == "CROSS_ARTIFACT_VARIANCE" for x in view.work_items)


def run():
    tests=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed=0
    for test in tests:
        try: test(); print(f"  PASS {test.__name__}")
        except Exception as exc: failed+=1; print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"  {len(tests)-failed}/{len(tests)} passed, {failed} failures")
    return failed
if __name__ == "__main__": raise SystemExit(1 if run() else 0)
