"""CP009.1 conservative sufficiency regression."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
os.environ['DRIFTGUARD_DEMO_MODE'] = '1'
from evidence.backbone import EvidenceAnalysis, analyze_artifacts
from evidence.mapping import map_questionnaire
from evidence.sufficiency import evaluate_sufficiency, DIMENSIONS, DimensionResult


def _dimensions(analysis, question='QN-ACCESS-001-Q01'):
    result = evaluate_sufficiency(analysis, map_questionnaire(analysis))
    record = next(r for r in result.requirements if r.question_id == question)
    return {d.dimension: d for d in record.dimensions}


def test_policy_does_not_establish_enforcement():
    analysis = analyze_artifacts([('mfa_policy.txt', b'Multi-factor authentication is required for production systems.')])
    d = _dimensions(analysis)
    assert d['presence'].state == 'NOT_ESTABLISHED'
    assert d['execution'].state == 'NOT_EVALUATED'
    assert d['scope'].state == 'NOT_EVALUATED'
    assert d['period'].state == 'NOT_EVALUATED'
    assert 'EV-IAM-001' in d['presence'].missing_facts


def test_empty_batch_is_not_control_failure():
    d = _dimensions(EvidenceAnalysis(()))
    assert tuple(d) == DIMENSIONS
    assert d['presence'].state == 'NOT_ESTABLISHED'
    assert d['consistency'].state == 'NOT_EVALUATED'
    assert 'control failure' in d['presence'].reason


def test_unmapped_question_remains_unevaluated():
    d = _dimensions(EvidenceAnalysis(()), 'QN-ACCESS-001-Q02')
    assert all(x.state == 'NOT_EVALUATED' for x in d.values())


def test_reproducible_versioned_serialization():
    a = EvidenceAnalysis(())
    one = evaluate_sufficiency(a, map_questionnaire(a)).to_dict()
    assert one == evaluate_sufficiency(a, map_questionnaire(a)).to_dict()
    assert one['schema_version'] == '1.0.0'
    assert len(one['requirements'][0]['dimensions']) == 8


def test_invalid_dimension_rejected():
    try:
        DimensionResult('invented', 'ESTABLISHED', (), (), 'reason', (), '')
    except ValueError:
        pass
    else:
        raise AssertionError('invalid dimension accepted')
