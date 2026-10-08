"""Semantic evaluation and grounded extraction run through the AI gateway (one path, one config).

Fake providers and fake SDK clients only; no network.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driftguard_platform import byoai
from driftguard_platform.ai import (
    AIOperation, AIProviderError, AIRequest, AIResult, AIOutputError, AnthropicProvider,
    OpenAIProvider, OpenRouterProvider, validate_result, AIValidationError,
)
from driftguard_platform.ai_gateway import AIGateway, CapabilityTable, GatewayPolicy
from driftguard_platform.ai_runtime import readiness, reset_gateway, run_with
from evaluation.engine import EvaluationEngine
from evaluation.execution import SemanticEvaluationRunner
from evaluation.providers.claude import (
    RESPONSE_SCHEMA, ClaudeOutputError, ClaudeProviderError, GatewaySemanticEvaluator,
)
from evaluation.semantic import SemanticResultValidationError, SemanticVerdict
from ingestion import Chunk, Document
from semantic_extraction import (
    FACT_SCHEMA, GatewayEvidenceProvider, SemanticSegmentRequest, build_request, extract_document,
)

QN, Q_SEM = "QN-ACCESS-001", "QN-ACCESS-001-Q09"
ANSWER = "We encrypt the primary database and its snapshots."
CAPS = CapabilityTable({"fake:m": {"json_mode": True, "context_tokens": 100000, "tool_use": False},
                        "anthropic:claude-haiku-4-5-20251001": {"json_mode": True, "context_tokens": 200000, "tool_use": True}})
VALID = {
    "assessment": SemanticVerdict.PARTIALLY_SUPPORTED.value, "confidence": 0.62,
    "present_elements": ["SE-002"], "missing_elements": ["SE-001", "SE-003"],
    "reason_codes": ["element_not_mentioned"], "needs_human_review": True,
    "indicates_finding": "FND-CRYPTO-001", "notes": ["Backups and replicas are not addressed."],
}
ENV = ("DRIFTGUARD_AI_PROVIDER", "DRIFTGUARD_AI_MODEL", "DRIFTGUARD_SEMANTIC_PROVIDER", "DRIFTGUARD_CLAUDE_MODEL",
       "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "DRIFTGUARD_AI_CONFIG_FILE",
       "DRIFTGUARD_AI_TIMEOUT_S", "DRIFTGUARD_AI_MAX_RETRIES", "DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS",
       "DRIFTGUARD_SEMANTIC_MAX_RETRIES")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(byoai, "_legacy_warned", False)
    reset_gateway(); yield; reset_gateway()


class Fake:
    """Fake provider; records every request it receives."""
    name, model = "fake", "m"
    def __init__(self, data=None, exc=None):
        self.data, self.exc, self.requests = data, exc, []
    def execute(self, request):
        self.requests.append(request)
        if self.exc: raise self.exc
        return validate_result(AIResult(request.operation, self.data, "fake", "m", request.source_ids,
                                        min(1.0, max(0.0, float(self.data.get("confidence", 0) if isinstance(self.data.get("confidence", 0), (int, float)) else 0)))))


def gw(provider, **policy):
    return AIGateway(provider, capabilities=CAPS, policy=GatewayPolicy(**policy), sleep=lambda s: None)


def knowledge():
    return EvaluationEngine.from_repository().knowledge


# ------------------------------------------------------------- semantic evaluation
def test_semantic_evaluation_through_gateway_is_still_validated():
    fake = Fake(VALID)
    ev = GatewaySemanticEvaluator(gw(fake))
    res = SemanticEvaluationRunner(knowledge(), ev).run(QN, Q_SEM, ANSWER)
    assert res.indicates_finding == "FND-CRYPTO-001"
    req = fake.requests[0]
    assert req.operation is AIOperation.SEMANTIC_EVALUATE and req.schema == RESPONSE_SCHEMA
    assert req.source_ids == ("SEMCOND-0001",) and req.system and req.max_output_tokens == 4096
    assert set(json.loads(req.content)) == {"condition_id", "question_id", "indicates_finding", "source_condition",
                                            "fires_when", "expected_elements", "answer_text"}


@pytest.mark.parametrize("verdict", [v.value for v in SemanticVerdict])
def test_every_semantic_verdict_survives_the_gateway(verdict):
    payload = {**VALID, "assessment": verdict}
    out = run_with(gw(Fake(payload)), AIRequest(AIOperation.SEMANTIC_EVALUATE, "{}", {}, ("SEMCOND-0001",), schema=RESPONSE_SCHEMA), "A")
    assert out.ok, out.detail


def test_free_text_with_pass_or_fail_words_is_not_rejected_by_the_gateway():
    payload = {**VALID, "notes": ["Password policy exists; a failed login lockout is described; backup test passed."]}
    out = run_with(gw(Fake(payload)), AIRequest(AIOperation.SEMANTIC_EVALUATE, "{}", {}, ("SEMCOND-0001",), schema=RESPONSE_SCHEMA), "A")
    assert out.ok, out.detail


def test_compliance_verdict_in_notes_is_still_rejected_downstream():
    ev = GatewaySemanticEvaluator(gw(Fake({**VALID, "notes": ["The organization is COMPLIANT."]})))
    with pytest.raises(SemanticResultValidationError):
        SemanticEvaluationRunner(knowledge(), ev).run(QN, Q_SEM, ANSWER)


def test_verdict_word_in_a_vocabulary_field_is_rejected_by_the_gateway():
    out = run_with(gw(Fake({**VALID, "assessment": "COMPLIANT"})),
                   AIRequest(AIOperation.SEMANTIC_EVALUATE, "{}", {}, ("SEMCOND-0001",), schema=RESPONSE_SCHEMA), "A")
    assert not out.ok and out.reason_code == "UNGROUNDED_OR_PROHIBITED_OUTPUT"


def test_legacy_operations_keep_the_whole_payload_substring_check():
    result = AIResult(AIOperation.CLASSIFY, {"note": "this PASSED"}, "fake", "m", ("S1",), 0.9)
    with pytest.raises(AIValidationError):
        validate_result(result)


def test_gateway_failure_becomes_provider_error_not_a_result():
    for fake in (Fake(exc=AIProviderError("boom")), Fake(exc=AIOutputError("empty"))):
        ev = GatewaySemanticEvaluator(gw(fake, max_retries=0))
        with pytest.raises(ClaudeProviderError):
            SemanticEvaluationRunner(knowledge(), ev).run(QN, Q_SEM, ANSWER)


def test_unusable_output_is_not_retried_and_maps_to_output_error():
    fake = Fake(exc=AIOutputError("not json"))
    out = gw(fake, max_retries=2).execute(AIRequest(AIOperation.SEMANTIC_EVALUATE, "{}", {}, ("S",)), "A")
    assert out.reason_code == "UNUSABLE_OUTPUT" and len(fake.requests) == 1
    ev = GatewaySemanticEvaluator(gw(Fake(exc=AIOutputError("not json"))))
    with pytest.raises(ClaudeOutputError):
        SemanticEvaluationRunner(knowledge(), ev).run(QN, Q_SEM, ANSWER)


def test_semantic_budget_is_separate_from_the_global_token_cap():
    fake = Fake(VALID)
    g = gw(fake, token_cap=10, semantic_token_cap=100000)
    assert g.execute(AIRequest(AIOperation.SEMANTIC_EVALUATE, "{}", {}, ("S",)), "A").ok
    assert not g.execute(AIRequest(AIOperation.CLASSIFY, "{}", {}, ("S",)), "A").ok   # global cap still binds the old operations


def test_unconfigured_gateway_evaluator_fails_to_construct_with_the_new_names(monkeypatch):
    with pytest.raises(ClaudeProviderError) as exc:
        GatewaySemanticEvaluator()
    assert "DRIFTGUARD_AI_PROVIDER" in str(exc.value)


# ------------------------------------------------------------------- extraction
def doc(text="Backup restore test passed on 2026-09-01."):
    return Document("e.txt", "artifact", (Chunk("e.txt", "line 1", text, heading="Backups", segment_type="line"),))


def fact(req, quote, value="success", attr="restore_result"):
    return {"facts": [{"concept": "backup", "attribute": attr, "value": value, "scope": ["prod"], "time": "current",
                       "claim_type": "OBSERVATION", "supporting_quote": quote, "source_locator": req.locator,
                       "confidence": 0.92, "reasoning_category": "direct", "source_role": req.document_role}]}


def test_extraction_through_gateway_accepts_legitimate_pass_fail_wording():
    d = doc()
    req = build_request(d, d.chunks[0], "UNKNOWN")
    fake = Fake(fact(req, d.chunks[0].text))
    facts, rejected = extract_document(d, GatewayEvidenceProvider(gw(fake)), "UNKNOWN")
    assert len(facts) == 1 and not rejected
    sent = fake.requests[0]
    assert sent.operation is AIOperation.EXTRACT_GROUNDED and sent.schema == FACT_SCHEMA
    assert sent.source_ids == ("e.txt#line 1",) and "untrusted_document_text" in sent.content


def test_validate_candidate_still_rejects_verdict_language_and_ungrounded_quotes():
    d = doc()
    req = build_request(d, d.chunks[0], "UNKNOWN")
    for payload, reason in ((fact(req, d.chunks[0].text, value="SOC 2 compliant"), "prohibited verdict language"),
                            (fact(req, "text that is not in the segment"), "supporting quote is not grounded in source segment")):
        facts, rejected = extract_document(d, GatewayEvidenceProvider(gw(Fake(payload))), "UNKNOWN")
        assert not facts and rejected[0].reason == reason


def test_extraction_gateway_failure_is_a_provider_error_rejection():
    d = doc()
    facts, rejected = extract_document(d, GatewayEvidenceProvider(gw(Fake(exc=AIProviderError("secret-token-123"), data={}), max_retries=0)), "UNKNOWN")
    assert not facts and rejected[0].reason == "provider error: RuntimeError"
    assert "secret" not in rejected[0].reason


# -------------------------------------------------------------------------- config
def test_new_variables_win_over_deprecated_ones(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_AI_PROVIDER", "openai"); monkeypatch.setenv("DRIFTGUARD_AI_MODEL", "gpt-5.6")
    monkeypatch.setenv("DRIFTGUARD_SEMANTIC_PROVIDER", "claude"); monkeypatch.setenv("DRIFTGUARD_CLAUDE_MODEL", "old")
    c = byoai.GatewayConfig.from_env()
    assert (c.provider, c.model) == ("openai", "gpt-5.6")


def test_deprecated_variables_still_configure_anthropic_and_warn_once(monkeypatch, caplog):
    monkeypatch.setenv("DRIFTGUARD_SEMANTIC_PROVIDER", "claude"); monkeypatch.setenv("DRIFTGUARD_CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    with pytest.warns(DeprecationWarning):
        c = byoai.GatewayConfig.from_env()
    assert (c.provider, c.model) == ("anthropic", "claude-haiku-4-5-20251001")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        byoai.GatewayConfig.from_env()   # second call must not warn again


def test_explicit_disabled_beats_the_deprecated_fallback(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_AI_PROVIDER", "disabled"); monkeypatch.setenv("DRIFTGUARD_SEMANTIC_PROVIDER", "claude")
    assert byoai.GatewayConfig.from_env().provider == "disabled"


def test_unknown_deprecated_provider_is_ignored(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_SEMANTIC_PROVIDER", "magic")
    assert byoai.GatewayConfig.from_env().provider == "disabled"


def test_readiness_names_missing_variables_and_never_returns_the_key(monkeypatch):
    assert set(readiness()["missing"]) == {"DRIFTGUARD_AI_PROVIDER", "DRIFTGUARD_AI_MODEL"}
    monkeypatch.setenv("DRIFTGUARD_AI_PROVIDER", "anthropic"); monkeypatch.setenv("DRIFTGUARD_AI_MODEL", "claude-haiku-4-5-20251001")
    assert readiness()["missing"] == ["ANTHROPIC_API_KEY"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-123456789")
    r = readiness()
    assert "sk-secret" not in json.dumps(r)
    assert r["ready"] in (True, False) and (r["ready"] or "SDK" in r["reason"])


def test_model_outside_the_capability_table_is_reported_not_silently_used(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_AI_PROVIDER", "anthropic"); monkeypatch.setenv("DRIFTGUARD_AI_MODEL", "not-a-listed-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x-123456789")
    r = readiness()
    assert not r["ready"] and "capability table" in r["reason"]


# --------------------------------------------------- provider structured-output plumbing
class _Resp:
    def __init__(self, **kw): self.__dict__.update(kw)


def _req(**kw):
    return AIRequest(AIOperation.SEMANTIC_EVALUATE, '{"x":1}', {}, ("S1",), schema={"type": "object"}, system="SYS", max_output_tokens=777, **kw)


def test_anthropic_sends_schema_system_and_verbatim_content():
    calls = []
    class M:
        def create(self, **kw):
            calls.append(kw)
            return _Resp(content=[_Resp(type="text", text=json.dumps(VALID))], stop_reason="end_turn", usage=None)
    p = AnthropicProvider(model="m", client=_Resp(messages=M()))
    out = p.execute(_req())
    kw = calls[0]
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert kw["system"] == "SYS" and kw["messages"][0]["content"] == '{"x":1}' and kw["max_tokens"] == 777
    assert out.data["assessment"] == VALID["assessment"] and out.source_ids == ("S1",)


def test_anthropic_structured_output_is_not_fence_stripped_or_repaired():
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    client = _Resp(messages=_Resp(create=lambda **kw: _Resp(content=[_Resp(type="text", text=fenced)], stop_reason="end_turn")))
    with pytest.raises(AIOutputError):
        AnthropicProvider(model="m", client=client).execute(_req())


def test_openai_and_openrouter_send_the_schema(monkeypatch):
    seen = {}
    class OAI:
        def __init__(self, **kw): self.kw = kw
        class _R:
            def create(self_, **kw): seen["openai"] = kw; return _Resp(output_text=json.dumps(VALID), usage=None)
        responses = _R()
        class _C:
            class completions:
                @staticmethod
                def create(**kw):
                    seen["openrouter"] = kw
                    return _Resp(choices=[_Resp(message=_Resp(content=json.dumps(VALID)))], usage=None)
        chat = _C()
    monkeypatch.setitem(sys.modules, "openai", _Resp(OpenAI=OAI))
    OpenAIProvider(api_key="k", model="m").execute(_req())
    OpenRouterProvider(api_key="k", model="m").execute(_req())
    assert seen["openai"]["text"]["format"]["type"] == "json_schema" and seen["openai"]["instructions"] == "SYS"
    assert seen["openai"]["input"] == '{"x":1}' and seen["openai"]["max_output_tokens"] == 777
    rf = seen["openrouter"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"] == {"type": "object"}
    assert seen["openrouter"]["messages"][0] == {"role": "system", "content": "SYS"}
