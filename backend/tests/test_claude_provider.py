#!/usr/bin/env python3
"""Tests for the Claude semantic evaluator adapter (Checkpoint 005).

NO network call is made. The Anthropic client boundary
(`client.messages.create(**kwargs)`) is replaced by fakes that record the
request and replay a canned response, so provider behaviour - including hostile
and broken behaviour - is exercised deterministically.

These tests cover the ADAPTER boundary (prompt construction, strict parsing,
fail-closed behaviour) plus the fact that CP004 still validates adapter output.
Validator internals stay in test_semantic_contract.py.

Run:  python backend/tests/run_tests.py
   or python backend/tests/test_claude_provider.py
"""

import json
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from evaluation.engine import EvaluationEngine  # noqa: E402
from evaluation.execution import SemanticEvaluationRunner  # noqa: E402
from evaluation.providers.claude import (  # noqa: E402
    ENV_MODEL,
    SYSTEM_PROMPT,
    ClaudeOutputError,
    ClaudeProviderError,
    ClaudeSemanticEvaluator,
)
from evaluation.semantic import (  # noqa: E402
    SemanticEvaluationResult,
    SemanticEvaluator,
    SemanticResultValidationError,
    SemanticVerdict,
    build_semantic_request,
)

QN = "QN-ACCESS-001"
Q_SEM = "QN-ACCESS-001-Q09"
SEMCOND = "SEMCOND-0001"
AUTHORIZED_FINDING = "FND-CRYPTO-001"
ANSWER = "We encrypt the primary database and its snapshots."

VALID_PAYLOAD = {
    "assessment": SemanticVerdict.PARTIALLY_SUPPORTED.value,
    "confidence": 0.62,
    "present_elements": ["SE-002"],
    "missing_elements": ["SE-001", "SE-003"],
    "reason_codes": ["element_not_mentioned"],
    "needs_human_review": True,
    "indicates_finding": AUTHORIZED_FINDING,
    "notes": ["Backups and replicas are not addressed by the answer."],
}


def _knowledge():
    return EvaluationEngine.from_repository().knowledge


def _request():
    return build_semantic_request(_knowledge(), QN, Q_SEM, ANSWER)


# ------------------------------------------------------- fake SDK boundary
class _TextBlock:
    """Stands in for an SDK TextBlock."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _ThinkingBlock:
    def __init__(self) -> None:
        self.type = "thinking"
        self.thinking = "internal reasoning that must not be parsed as JSON"


class _Message:
    def __init__(self, blocks, stop_reason="end_turn") -> None:
        self.content = blocks
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, behaviour) -> None:
        self._behaviour = behaviour
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._behaviour, Exception):
            raise self._behaviour
        return self._behaviour


class FakeClient:
    """Fake Anthropic client: exposes exactly `client.messages.create(**kwargs)`."""

    def __init__(self, behaviour) -> None:
        self.messages = _Messages(behaviour)

    @classmethod
    def replying(cls, text: str, stop_reason: str = "end_turn") -> "FakeClient":
        return cls(_Message([_ThinkingBlock(), _TextBlock(text)], stop_reason))

    @classmethod
    def replying_json(cls, payload: dict) -> "FakeClient":
        return cls.replying(json.dumps(payload))

    @classmethod
    def raising(cls, exc: Exception) -> "FakeClient":
        return cls(exc)


TEST_MODEL = "test-model-not-called"


def _evaluator(client) -> ClaudeSemanticEvaluator:
    return ClaudeSemanticEvaluator(client, model=TEST_MODEL)


def _expect_output_error(label: str, client) -> None:
    try:
        _evaluator(client).evaluate(_request())
    except ClaudeOutputError:
        return
    raise AssertionError(f"{label} did not fail closed")


# ---------------------------------------------------------------------- 1
def test_1_valid_provider_json_becomes_result():
    evaluator = _evaluator(FakeClient.replying_json(VALID_PAYLOAD))
    req = _request()
    out = evaluator.evaluate(req)

    assert isinstance(out, SemanticEvaluationResult)
    assert isinstance(evaluator, SemanticEvaluator)          # satisfies the CP003 contract
    assert out.assessment == VALID_PAYLOAD["assessment"]
    assert out.confidence == VALID_PAYLOAD["confidence"]
    assert out.present_elements == ("SE-002",)
    assert out.missing_elements == ("SE-001", "SE-003")
    assert out.reason_codes == ("element_not_mentioned",)
    assert out.needs_human_review is True
    assert out.indicates_finding == AUTHORIZED_FINDING
    assert out.notes == tuple(VALID_PAYLOAD["notes"])
    # Identity comes from the grounded request, not from the model.
    assert out.condition_id == req.condition_id
    assert out.question_id == req.question_id
    assert out.result_id.startswith("SEMRES-CLAUDE-")
    # result_id is unique per evaluation run.
    again = _evaluator(FakeClient.replying_json(VALID_PAYLOAD)).evaluate(req)
    assert again.result_id != out.result_id


# ---------------------------------------------------------------------- 2
def test_2_malformed_json_fails_closed():
    _expect_output_error("malformed JSON", FakeClient.replying("{not json at all"))
    _expect_output_error("JSON array instead of object", FakeClient.replying('["SUPPORTED"]'))
    # A fenced code block is not silently unwrapped.
    _expect_output_error(
        "fenced JSON",
        FakeClient.replying("```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"),
    )


# ---------------------------------------------------------------------- 3
def test_3_empty_response_fails_closed():
    _expect_output_error("no content blocks", FakeClient(_Message([])))
    _expect_output_error("blank text", FakeClient.replying("   \n  "))
    # Only non-text blocks: nothing parseable was returned.
    _expect_output_error("thinking-only response", FakeClient(_Message([_ThinkingBlock()])))
    # Truncated output must never be parsed as if complete.
    _expect_output_error(
        "truncated response",
        FakeClient.replying(json.dumps(VALID_PAYLOAD), stop_reason="max_tokens"),
    )


# ---------------------------------------------------------------------- 4
def test_4_provider_exception_fails_closed():
    try:
        _evaluator(FakeClient.raising(RuntimeError("connection reset"))).evaluate(_request())
    except ClaudeProviderError as exc:
        assert "connection reset" in str(exc)
    else:
        raise AssertionError("provider exception did not fail closed")


# ---------------------------------------------------------------------- 5
def test_5_missing_required_field_fails_closed():
    for field in ("assessment", "confidence", "reason_codes", "needs_human_review",
                  "present_elements", "missing_elements"):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != field}
        _expect_output_error(f"missing {field}", FakeClient.replying_json(payload))

    # An unexpected field is unsafe structure, not something to ignore.
    _expect_output_error(
        "smuggled extra field",
        FakeClient.replying_json({**VALID_PAYLOAD, "soc2_status": "PASSED"}),
    )


# ---------------------------------------------------------------------- 6
def test_6_wrong_field_type_fails_closed():
    cases = {
        "assessment": 7,
        "confidence": "0.62",                 # string, not coerced to a number
        "needs_human_review": "yes",          # string, not coerced to a bool
        "present_elements": "SE-002",         # string, not wrapped in a list
        "missing_elements": [1, 2],
        "reason_codes": {"code": "low_confidence"},
        "indicates_finding": ["FND-CRYPTO-001"],
        "notes": "one note",
    }
    for field, bad in cases.items():
        _expect_output_error(
            f"wrong type for {field}",
            FakeClient.replying_json({**VALID_PAYLOAD, field: bad}),
        )

    # A boolean is not accepted as a number.
    _expect_output_error(
        "boolean confidence",
        FakeClient.replying_json({**VALID_PAYLOAD, "confidence": True}),
    )


# ---------------------------------------------------------------------- 7
def test_7_prompt_carries_the_grounded_request():
    client = FakeClient.replying_json(VALID_PAYLOAD)
    evaluator = _evaluator(client)
    req = _request()
    evaluator.evaluate(req)

    assert len(client.messages.calls) == 1
    kwargs = client.messages.calls[0]
    assert kwargs["model"] == TEST_MODEL
    assert kwargs["system"] == SYSTEM_PROMPT
    # Structured, machine-readable output is requested at the API level.
    fmt = kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False

    sent = json.loads(kwargs["messages"][0]["content"])
    assert sent == req.to_dict()
    assert sent["condition_id"] == SEMCOND
    assert sent["question_id"] == Q_SEM
    assert sent["indicates_finding"] == AUTHORIZED_FINDING
    assert sent["fires_when"] == "any_required_element_missing"
    assert sent["answer_text"] == ANSWER
    assert [e["element_id"] for e in sent["expected_elements"]] == ["SE-001", "SE-002", "SE-003"]
    assert sent["source_condition"]

    # The instructions actually constrain the model.
    lowered = SYSTEM_PROMPT.lower()
    for phrase in ("only the supplied condition", "do not use any outside soc 2",
                   "do not invent", "never state or imply soc 2 compliance"):
        assert phrase in lowered

    # No model id is assumed: with nothing configured, construction fails clearly.
    saved = os.environ.pop(ENV_MODEL, None)
    try:
        ClaudeSemanticEvaluator(client)
    except ClaudeProviderError as exc:
        assert ENV_MODEL in str(exc)
    else:
        raise AssertionError("missing model configuration was not rejected")
    finally:
        if saved is not None:
            os.environ[ENV_MODEL] = saved


# ---------------------------------------------------------------------- 8
def test_8_prompt_contains_no_unrelated_knowledge():
    client = FakeClient.replying_json(VALID_PAYLOAD)
    _evaluator(client).evaluate(_request())
    kwargs = client.messages.calls[0]

    sent = json.loads(kwargs["messages"][0]["content"])
    # Exactly the grounded request fields - nothing else is transmitted.
    assert set(sent) == {
        "condition_id", "question_id", "indicates_finding", "source_condition",
        "fires_when", "expected_elements", "answer_text",
    }

    blob = json.dumps(kwargs, sort_keys=True)
    # No other knowledge record of any kind leaks into the request.
    for foreign in ("SEMCOND-0002", "FND-IAM-001", "SOC2-CC6", "EV-", "POL-",
                    "REM-", "MAP-", "QN-ACCESS-001-Q01", "trust_services_criteria"):
        assert foreign not in blob, f"unrelated knowledge {foreign!r} reached the provider"

    # The whole request stays small (prompt is compact by construction).
    assert len(blob) < 4000


# ---------------------------------------------------------------------- 9
def test_9_cp004_runner_validates_and_rejects_provider_output():
    knowledge = _knowledge()

    # Happy path: the adapter plugs into the CP004 runner unchanged.
    ok = SemanticEvaluationRunner(
        knowledge, _evaluator(FakeClient.replying_json(VALID_PAYLOAD))
    ).run(QN, Q_SEM, ANSWER)
    assert ok.indicates_finding == AUTHORIZED_FINDING

    # Hostile provider output that is structurally valid still has to survive
    # CP003 grounding/authorization checks through the runner.
    hostile = {
        "invented finding": {"indicates_finding": "FND-INVENTED-999"},
        "unauthorized known finding": {"indicates_finding": "FND-IAM-001"},
        "ungrounded element": {"present_elements": ["SE-042"]},
        "out-of-range confidence": {"confidence": 3.0},
        "unknown reason code": {"reason_codes": ["seems_fine"]},
        "compliance conclusion in notes": {"notes": ["The organization is COMPLIANT."]},
        "invalid verdict": {"assessment": "MOSTLY_SUPPORTED"},
    }
    for label, override in hostile.items():
        runner = SemanticEvaluationRunner(
            knowledge,
            _evaluator(FakeClient.replying_json({**VALID_PAYLOAD, **override})),
        )
        try:
            runner.run(QN, Q_SEM, ANSWER)
        except SemanticResultValidationError:
            continue
        raise AssertionError(f"CP004/CP003 accepted provider output with {label}")


TESTS = [
    test_1_valid_provider_json_becomes_result,
    test_2_malformed_json_fails_closed,
    test_3_empty_response_fails_closed,
    test_4_provider_exception_fails_closed,
    test_5_missing_required_field_fails_closed,
    test_6_wrong_field_type_fails_closed,
    test_7_prompt_carries_the_grounded_request,
    test_8_prompt_contains_no_unrelated_knowledge,
    test_9_cp004_runner_validates_and_rejects_provider_output,
]


def run() -> int:
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  ok    {t.__name__}")
        except Exception as e:  # noqa: BLE001 - harness reports every failure
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if failed else 'PASSED'}: {failed} failure(s)")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
