#!/usr/bin/env python3
"""A framework is knowledge files only: a 3-control ISO27001 stub, no code changes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driftguard_platform.frameworks import FrameworkRegistry, registry
from evidence.backbone import (ArtifactFact, ArtifactProvenance, EvidenceAnalysis,
                               EvidenceArtifact)
from evidence.knowledge import load_controls, load_questionnaire
from evidence.mapping import NOT_EVALUATED, OBSERVED, REQUEST, map_questionnaire
from evidence.sufficiency import evaluate_sufficiency

STUB = Path(__file__).resolve().parent / "fixtures" / "knowledge_iso27001_stub"
SOC2 = Path(__file__).resolve().parents[2] / "knowledge" / "soc2"


def _artifact(evidence_id):
    prov = (ArtifactProvenance("stub.csv", "A1"),)
    fact = ArtifactFact("stub.fact", "Stub", "x", "observed", "test", prov)
    return EvidenceArtifact("art-1", "stub.csv", "csv", "STRUCTURED_EVIDENCE", "stub",
                            evidence_id, "CLASSIFIED", False, (fact,), ())


def test_stub_framework_registers_from_knowledge_files_only():
    reg = FrameworkRegistry()
    fw = reg.load_directory(STUB)
    assert (fw.key, fw.version) == ("ISO27001", "2022")
    assert fw.controls == frozenset({"A.5.15", "A.5.17", "A.8.15"})
    assert reg.get("ISO27001", "2022") is fw


def test_controls_and_questions_carry_framework_id_and_version():
    controls = load_controls(STUB)
    assert len(controls) == 3
    assert {(c["framework"], c["framework_version"]) for c in controls} == {("ISO27001", "2022")}
    qn = load_questionnaire("QN-ISO-STUB-001", STUB)
    assert {(q["framework"], q["framework_version"]) for q in qn["questions"]} == {("ISO27001", "2022")}


def test_stub_maps_through_the_same_engine():
    analysis = EvidenceAnalysis((_artifact("EV-STUB-001"),))
    view = map_questionnaire(analysis, "QN-ISO-STUB-001", knowledge_root=STUB)
    assert (view.framework, view.framework_version) == ("ISO27001", "2022")
    by_id = {q.question_id: q for q in view.questions}
    assert by_id["QN-ISO-STUB-001-Q01"].state == OBSERVED
    assert by_id["QN-ISO-STUB-001-Q02"].state == NOT_EVALUATED   # not in mapping_profile
    assert by_id["QN-ISO-STUB-001-Q03"].state == REQUEST         # EV-STUB-002 not supplied
    assert {(q.framework, q.framework_version) for q in view.questions} == {("ISO27001", "2022")}
    assert evaluate_sufficiency(analysis, view).to_dict()  # downstream stages accept it
    assert "compliance_verdict" not in str(view.to_dict()).lower()


def test_soc2_identity_and_registry_unchanged():
    view = map_questionnaire(EvidenceAnalysis(()), knowledge_root=SOC2)
    assert (view.framework, view.framework_version) == ("SOC2", "2017")
    evaluated = [q.question_id[-3:] for q in view.questions if q.state != NOT_EVALUATED]
    assert evaluated == ["Q01", "Q03", "Q04", "Q05", "Q06"]
    soc2 = registry.get("SOC2", "2017")
    assert soc2.controls == frozenset({"CC6", "CC7"})
    assert {c["framework"] for c in load_controls(SOC2)} == {"SOC2"}
