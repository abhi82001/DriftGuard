#!/usr/bin/env python3
"""CP008 tests for the format-neutral evidence-analysis backbone."""

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DRIFTGUARD_DEMO_MODE"] = "1"

from evidence import UNCLASSIFIED, USER_ACCESS_REVIEW  # noqa: E402
from evidence.backbone import (  # noqa: E402
    DOCUMENT_TEXT,
    STRUCTURED_EVIDENCE,
    analyze_artifacts,
)
from fixtures import user_access_review_fixture as fx  # noqa: E402


def test_1_mixed_formats_share_one_contract():
    policy = (
        "Access Control Policy\n\n"
        "Multi-factor authentication is required for production systems.\n"
    ).encode()
    result = analyze_artifacts([
        ("Access_Control_Policy.txt", policy),
        (fx.REAL_FILENAME, fx.real_workbook()),
    ])

    assert not result.errors
    assert len(result.artifacts) == 2

    text = result.artifact("Access_Control_Policy.txt")
    assert text is not None
    assert text.format == "txt"
    assert text.document_kind == "policy"
    assert text.evidence_type == UNCLASSIFIED
    assert text.state == "OBSERVED"
    assert text.facts_for("mfa.requirement")[0].value == "required"
    assert text.facts_for("mfa.requirement")[0].source_layer == DOCUMENT_TEXT
    assert text.facts_for("mfa.requirement")[0].provenance[0].locator.startswith("lines")

    sheet = result.artifact(fx.REAL_FILENAME)
    assert sheet is not None
    assert sheet.format == "xlsx"
    assert sheet.evidence_type == USER_ACCESS_REVIEW
    assert sheet.knowledge_evidence_id == "EV-ACCESS-001"
    assert sheet.facts_for("reviewed_population")[0].value == 5
    assert sheet.facts_for("reviewed_population")[0].source_layer == STRUCTURED_EVIDENCE
    assert sheet.facts_for("reviewed_population")[0].provenance[0].container == "Access Review"
    assert sheet.checks


def test_2_tabular_cp007_miss_does_not_erase_cp006_claims():
    data = (
        "application,authentication policy,state\n"
        "identity provider,multi-factor authentication,enforced\n"
    ).encode()
    result = analyze_artifacts([("idp_mfa_configuration_export.csv", data)])
    artifact = result.artifacts[0]

    assert artifact.evidence_type == UNCLASSIFIED
    assert artifact.state == "OBSERVED"
    assert artifact.facts_for("mfa.enforcement_evidence")
    assert artifact.facts_for("mfa.enforcement_evidence")[0].value is True


def test_3_artifact_id_is_stable_and_content_sensitive():
    first = analyze_artifacts([("evidence.txt", b"MFA is required.")]).artifacts[0]
    again = analyze_artifacts([("evidence.txt", b"MFA is required.")]).artifacts[0]
    changed = analyze_artifacts([("evidence.txt", b"MFA is enforced.")]).artifacts[0]

    assert first.artifact_id == again.artifact_id
    assert first.artifact_id != changed.artifact_id


def test_4_bad_upload_isolated_as_error():
    result = analyze_artifacts([
        ("good.txt", b"MFA is required."),
        ("bad.exe", b"not supported"),
    ])
    assert len(result.artifacts) == 1
    assert result.artifacts[0].filename == "good.txt"
    assert len(result.errors) == 1
    assert "unsupported file type" in result.errors[0]


def test_5_serialization_keeps_provenance_and_no_compliance_verdict():
    result = analyze_artifacts([(fx.REAL_FILENAME, fx.real_workbook())])
    payload = result.to_dict()
    artifact = payload["artifacts"][0]

    assert artifact["record_type"] == "evidence_artifact"
    fact = next(f for f in artifact["facts"] if f["key"] == "reviewed_population")
    assert fact["provenance"][0]["filename"] == fx.REAL_FILENAME
    assert fact["provenance"][0]["container"] == "Access Review"
    assert "compliance_verdict" not in artifact
    assert "control_status" not in artifact


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"  {len(tests) - failed}/{len(tests)} passed, {failed} failures")
    return failed


if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)
