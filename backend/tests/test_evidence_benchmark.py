#!/usr/bin/env python3
"""CP008 evidence vocabulary and format benchmark regression gate."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / 'src'
sys.path.insert(0, str(SRC))
os.environ['DRIFTGUARD_DEMO_MODE'] = '1'

from evidence.backbone import analyze_artifacts  # noqa: E402
from evidence.benchmark import evaluate_cases  # noqa: E402

BENCH = HERE / 'evidence_benchmark'


def test_1_vocabulary_ground_truth():
    cases = json.loads((BENCH / 'cases.json').read_text(encoding='utf-8'))
    metrics, failures = evaluate_cases(cases)
    assert len(cases) >= 120
    assert metrics.target_recall >= 0.98, (metrics.to_dict(), failures[:10])
    assert metrics.false_inference_rate == 0.0, (metrics.to_dict(), failures[:10])


def test_2_all_supported_formats_preserve_grounded_mfa_fact():
    files = []
    for path in sorted((BENCH / 'formats').iterdir()):
        files.append((path.name, path.read_bytes()))
    result = analyze_artifacts(files)
    assert not result.errors, result.errors
    assert {a.format for a in result.artifacts} == {'txt','md','csv','xlsx','docx','pdf'}
    for artifact in result.artifacts:
        facts = artifact.facts_for('mfa.requirement')
        assert facts, artifact.filename
        assert facts[0].value == 'required'
        assert facts[0].provenance, artifact.filename


def test_3_benchmark_reports_measured_not_claimed_accuracy():
    cases = json.loads((BENCH / 'cases.json').read_text(encoding='utf-8'))
    metrics, _ = evaluate_cases(cases)
    payload = metrics.to_dict()
    assert payload['cases'] == len(cases)
    assert 0 <= payload['target_recall'] <= 1
    assert 0 <= payload['false_inference_rate'] <= 1
    assert 'accuracy' not in payload  # avoid unsupported one-number claims


def run():
    tests = [v for k,v in sorted(globals().items()) if k.startswith('test_') and callable(v)]
    failed=0
    for test in tests:
        try:
            test(); print(f'  PASS {test.__name__}')
        except Exception as exc:
            failed+=1; print(f'  FAIL {test.__name__}: {type(exc).__name__}: {exc}')
    print(f'  {len(tests)-failed}/{len(tests)} passed, {failed} failures')
    return failed

if __name__=='__main__': raise SystemExit(1 if run() else 0)
