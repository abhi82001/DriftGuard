"""AI gateway tests. Fake providers only; any socket connect fails the test (no network)."""
import json, socket, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driftguard_platform.ai import (AIOperation, AIProviderError, AIRegistry, AIRequest, AIResult, AIUnavailable,
                                    DisabledAIProvider, registry as default_registry)
from driftguard_platform.ai_gateway import (AIGateway, AICompatibilityError, CapabilityTable, GatewayPolicy,
                                            check_compatibility, STATUS_OK, STATUS_UNAVAILABLE)
from driftguard_platform.byoai import GatewayConfig, gateway_from_config

CAPS = CapabilityTable({
    "fake:m1": {"json_mode": True, "context_tokens": 100000, "tool_use": True, "price_in_per_mtok": 1.0, "price_out_per_mtok": 2.0},
    "fake:m2": {"json_mode": True, "context_tokens": 100000, "tool_use": False, "price_in_per_mtok": 1.0, "price_out_per_mtok": 2.0},
    "fake:nojson": {"json_mode": False, "context_tokens": 100000, "tool_use": False},
    "fake:tiny": {"json_mode": True, "context_tokens": 100, "tool_use": False},
})
REQ = AIRequest(AIOperation.CLASSIFY, "Sheet Access Review", source_ids=("ART-1",))
SLEEPS: list = []


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real = socket.socket.connect
    def guarded(self, address, *a, **k):   # loopback is allowed (asyncio self-pipe); anything else is a network call
        if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
            raise AssertionError(f"network access attempted in test: {address!r}")
        return real(self, address, *a, **k)
    monkeypatch.setattr(socket.socket, "connect", guarded)
    SLEEPS.clear()


class Fake:
    def __init__(self, name="fake", model="m1", script=None, data=None, source_ids=None, usage=None):
        self.name, self.model, self.calls = name, model, 0
        self.script = list(script or [])           # exceptions to raise first, in order
        self.data = data if data is not None else {"artifact_type": "user_access_review", "confidence": 0.9}
        self.source_ids = source_ids if source_ids is not None else ("ART-1",)
        self.usage = usage if usage is not None else {"input_tokens": 100, "output_tokens": 50}
    def execute(self, request):
        self.calls += 1
        if self.script:
            e = self.script.pop(0)
            if e: raise e
        return AIResult(request.operation, self.data, self.name, self.model, self.source_ids, 0.9, (), self.usage, request.correlation_id)


def gw(primary, fallback=None, **policy):
    policy.setdefault("backoff_base_s", 0.1)
    return AIGateway(primary, fallback, capabilities=CAPS, policy=GatewayPolicy(**policy), sleep=SLEEPS.append, secrets=["sk-SECRET-123456"])


def test_success_records_usage():
    g = gw(Fake(), cost_cap_usd=1.0)
    out = g.execute(REQ, "A1")
    assert out.status == STATUS_OK and out.result.data["artifact_type"] == "user_access_review"
    assert out.tokens == 150 and out.cost_usd == pytest.approx((100 * 1 + 50 * 2) / 1e6)
    assert g.ledger.get("A1").calls == 1


def test_disabled_by_default_is_unavailable_not_error():
    out = AIGateway(DisabledAIProvider(), capabilities=CAPS).execute(REQ)
    assert out.status == STATUS_UNAVAILABLE and out.reason_code == "AI_DISABLED"
    assert out.as_record()["status"] == "AI unavailable" and out.as_record()["deterministic_results_affected"] is False
    cfg = gateway_from_config(GatewayConfig(), default_registry, None)
    assert cfg.execute(REQ).reason_code == "AI_DISABLED"


def test_retry_with_backoff_then_success():
    p = Fake(script=[AIProviderError("boom"), AIProviderError("boom")])
    out = gw(p, max_retries=2).execute(REQ)
    assert out.ok and out.attempts == 3 and SLEEPS == [0.1, 0.2]


def test_retries_exhausted_is_unavailable_and_timeout_coded():
    p = Fake(script=[TimeoutError("t")] * 5)
    out = gw(p, max_retries=1).execute(REQ)
    assert not out.ok and out.reason_code == "TIMEOUT" and p.calls == 2 and out.result is None


def test_missing_key_not_retried():
    p = Fake(script=[AIUnavailable("KEY missing")])
    out = gw(p, max_retries=3).execute(REQ)
    assert out.reason_code == "PROVIDER_UNAVAILABLE" and p.calls == 1 and SLEEPS == []


def test_fallback_used_after_primary_fails():
    primary = Fake(script=[AIProviderError("x")] * 5)
    fb = Fake(model="m2")
    out = gw(primary, fb, max_retries=1).execute(REQ)
    assert out.ok and out.fallback_used and out.model == "m2" and primary.calls == 2 and fb.calls == 1


def test_both_fail_reports_unavailable():
    out = gw(Fake(script=[AIProviderError("x")] * 5), Fake(model="m2", script=[AIProviderError("y")] * 5), max_retries=0).execute(REQ)
    assert not out.ok and out.fallback_used


def test_token_cap_blocks_before_call():
    p = Fake()
    out = gw(p, token_cap=300, max_output_tokens=400).execute(REQ, "A2")
    assert out.reason_code == "BUDGET_EXCEEDED" and p.calls == 0


def test_cap_is_per_assessment_and_accumulates():
    p = Fake()
    g = gw(p, token_cap=400, max_output_tokens=100)
    assert g.execute(REQ, "A").ok and g.execute(REQ, "A").ok       # 150 each; a third would exceed
    assert g.execute(REQ, "A").reason_code == "BUDGET_EXCEEDED"
    assert g.execute(REQ, "B").ok                                  # other assessment unaffected
    assert p.calls == 3


def test_cost_cap_blocks_and_needs_a_price():
    assert gw(Fake(), cost_cap_usd=0.0000001, max_output_tokens=100).execute(REQ).reason_code == "BUDGET_EXCEEDED"
    out = gw(Fake(model="tiny"), cost_cap_usd=1.0).execute(REQ)
    assert out.reason_code in {"PRICE_UNKNOWN", "CONTEXT_TOO_SMALL"}
    unpriced = CapabilityTable({"fake:np": {"json_mode": True, "context_tokens": 9999}}).get("fake", "np")
    with pytest.raises(AICompatibilityError) as e:
        check_compatibility(unpriced, "fake", "np", REQ, max_output_tokens=10, need_price=True)
    assert e.value.code == "PRICE_UNKNOWN"


@pytest.mark.parametrize("model,code", [("unlisted", "UNKNOWN_MODEL"), ("nojson", "NO_JSON_MODE"), ("tiny", "CONTEXT_TOO_SMALL")])
def test_compatibility_typed_errors_before_call(model, code):
    p = Fake(model=model)
    with pytest.raises(AICompatibilityError) as e:
        check_compatibility(CAPS.get("fake", model), "fake", model, REQ, max_output_tokens=2048)
    assert e.value.code == code
    out = gw(p).execute(REQ)
    assert out.reason_code == code and p.calls == 0


def test_ungrounded_output_rejected():
    for sids in [(), ("ART-9",)]:
        out = gw(Fake(source_ids=sids)).execute(REQ)
        assert out.reason_code == "UNGROUNDED_OR_PROHIBITED_OUTPUT" and out.result is None
    assert not gw(Fake(data={"a": 1, "source_ids": ["ART-9"]})).execute(REQ).ok
    assert not gw(Fake()).execute(AIRequest(AIOperation.CLASSIFY, "x")).ok      # request without source_ids


@pytest.mark.parametrize("word", ["COMPLIANT", "NON_COMPLIANT", "PASS", "FAIL", "CERTIFIED", "AUDIT_OPINION", "SOC2_PASSED", "QUALIFIED_OPINION"])
def test_verdict_words_rejected(word):
    out = gw(Fake(data={"summary": f"overall {word.lower()}"})).execute(REQ)
    assert out.reason_code == "UNGROUNDED_OR_PROHIBITED_OUTPUT"


def test_failure_never_changes_deterministic_result():
    def deterministic(): return {"gaps": ["G1", "G2"]}
    before = deterministic()
    out = gw(Fake(script=[AIProviderError("x")] * 9), max_retries=0).execute(REQ)
    assert not out.ok and deterministic() == before


def test_secrets_scrubbed_from_recorded_detail():
    out = gw(Fake(script=[AIProviderError("bad key sk-SECRET-123456 and Bearer abcdef")]), max_retries=0).execute(REQ)
    blob = json.dumps(out.as_record())
    assert "SECRET-123456" not in blob and "abcdef" not in blob


def test_switching_by_config_only():
    r = AIRegistry()
    seen = []
    r.register("fake", lambda **kw: seen.append(kw) or Fake(model=kw.get("model", "m1")))
    class Sec:
        def get(self, ref): return "sk-SECRET-123456"
    g1 = gateway_from_config(GatewayConfig(provider="fake", model="m1", secret_refs={"fake": "X"}), r, Sec(), capabilities=CAPS)
    g2 = gateway_from_config(GatewayConfig(provider="fake", model="m2", fallback_provider="fake", fallback_model="m1",
                                           secret_refs={"fake": "X"}), r, Sec(), capabilities=CAPS)
    assert g1.primary.model == "m1" and g2.primary.model == "m2" and g2.fallback.model == "m1"
    assert seen[0]["api_key"] == "sk-SECRET-123456" and g1.scrub("sk-SECRET-123456") == "[redacted]"


def test_config_file_rejects_inline_secrets_and_unknown_fields():
    with pytest.raises(ValueError): GatewayConfig.from_mapping({"provider": "openai", "api_key": "sk-x"})
    with pytest.raises(ValueError): GatewayConfig.from_mapping({"provider": "openai", "bogus": 1})
    assert GatewayConfig.from_mapping({"provider": "openai", "model": "gpt-5.6", "secret_refs": {"openai": "OPENAI_API_KEY"}}).model == "gpt-5.6"


def test_registry_has_all_adapters_and_default_table_loads():
    for n in ("openai", "anthropic", "openrouter", "disabled"): assert default_registry.create(n)
    assert CapabilityTable.load().get("anthropic", "claude-sonnet-5-5").json_mode


def test_capabilities_endpoint_leaks_no_secrets(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"): monkeypatch.setenv(k, "sk-LEAKCHECK-999999")
    monkeypatch.setenv("DRIFTGUARD_AI_PROVIDER", "openai"); monkeypatch.setenv("DRIFTGUARD_AI_MODEL", "gpt-5.6")
    from starlette.testclient import TestClient
    import app as app_module
    r = TestClient(app_module.app).get("/api/v1/ai/capabilities")
    assert r.status_code == 200 and "LEAKCHECK" not in r.text and "gpt-5.6" not in r.text
    assert set(r.json()) == {"provider_neutral", "operations", "authoritative_compliance_verdicts", "default_mode"}
