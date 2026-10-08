"""AI call sites route through AIGateway and degrade safely. Fake providers only."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from driftguard_platform.ai import AIResult, DisabledAIProvider
from driftguard_platform.ai_gateway import AIGateway, CapabilityTable, GatewayPolicy
from driftguard_platform.ai_runtime import get_gateway, reset_gateway, run_ai
from driftguard_platform.ai import AIOperation, AIRequest
from driftguard_platform.assistant import AssistantContext, grounded_answer, INSUFFICIENT
from driftguard_platform.byoai import GatewayConfig, DEFAULT_TOKEN_CAP
from driftguard_platform.intelligence import classify_unknown, extract_candidate_facts
from evidence.ai_mapping import infer_with_ai
from evidence.tabular import read_tabular

CAPS = CapabilityTable({"fake:m": {"json_mode": True, "context_tokens": 100000, "tool_use": False}})
CSV = ("x.csv", b"Job Label,Kickoff,Disposition\napi,2026-10-01,Successful\ndb,2026-10-02,Failed\n")
GOOD = {"role": "BACKUP_JOB_REPORT", "map": {"system": "job label", "scheduled": "kickoff", "result": "disposition"}}


class Fake:
    name, model = "fake", "m"
    def __init__(self, data=None): self.data, self.calls = data if data is not None else GOOD, 0
    def execute(self, request):
        self.calls += 1
        return AIResult(request.operation, self.data, "fake", "m", request.source_ids, 0.93)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("DRIFTGUARD_AI_PROVIDER", "DRIFTGUARD_AI_TOKEN_CAP", "DRIFTGUARD_AI_CONFIG_FILE", "DRIFTGUARD_MAPPING_STORE"):
        monkeypatch.delenv(k, raising=False)
    reset_gateway(); yield; reset_gateway()


def gateway(provider, **policy): return AIGateway(provider, capabilities=CAPS, policy=GatewayPolicy(**policy))
def book(): return read_tabular(*CSV)
def ctx(sources=("S1",)): return AssistantContext("t", sources, (), {})


def test_default_is_disabled_and_cap_is_20000():
    cfg = GatewayConfig.from_env()
    assert cfg.provider == "disabled" and cfg.token_cap == DEFAULT_TOKEN_CAP == 20000
    out = run_ai(AIRequest(AIOperation.CLASSIFY, "x", source_ids=("S1",)))
    assert not out.ok and out.reason_code == "AI_DISABLED"


def test_token_cap_env_override(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_AI_TOKEN_CAP", "1234")
    assert GatewayConfig.from_env().token_cap == 1234


def test_gateway_is_cached_until_reset():
    a = get_gateway(); assert get_gateway() is a
    reset_gateway(); assert get_gateway() is not a


def test_tiny_token_cap_stops_infer_with_ai_with_zero_calls():
    fake = Fake()
    assert infer_with_ai(book(), gateway(fake, token_cap=10)) is None
    assert fake.calls == 0


def test_infer_with_ai_through_gateway_succeeds_with_headroom():
    fake = Fake()
    assert infer_with_ai(book(), gateway(fake, token_cap=20000)).role == "BACKUP_JOB_REPORT" and fake.calls == 1


def test_infer_with_ai_unavailable_stays_unclassified():
    assert infer_with_ai(book(), gateway(DisabledAIProvider())) is None
    assert infer_with_ai(book()) is None   # process gateway, disabled by default


def test_classify_unknown_degrades():
    r = classify_unknown(gateway(DisabledAIProvider()), content="c", source_id="S1")
    assert (r.artifact_type, r.confidence) == ("UNCLASSIFIED", 0.0)


def test_extract_candidate_facts_degrades():
    assert extract_candidate_facts(gateway(DisabledAIProvider()), content="c", source_id="S1") == ()
    assert extract_candidate_facts(gateway(Fake(), token_cap=10), content="c", source_id="S1") == ()


def test_grounded_answer_degrades():
    assert grounded_answer(gateway(DisabledAIProvider()), "q?", ctx()) == INSUFFICIENT
    assert grounded_answer(gateway(Fake(), token_cap=10), "q?", ctx()) == INSUFFICIENT


def test_prohibited_verdict_from_provider_is_rejected():
    bad = Fake({"answer": "PASS"})
    assert grounded_answer(bad, "q?", ctx()) == INSUFFICIENT
    assert grounded_answer(gateway(Fake({"answer": "SOC2_PASSED"})), "q?", ctx()) == INSUFFICIENT


def test_grounded_answer_returns_answer_through_gateway():
    assert grounded_answer(gateway(Fake({"answer": "Because."})), "q?", ctx()) == "Because."
