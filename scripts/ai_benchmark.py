#!/usr/bin/env python3
"""Run the AI benchmark fixtures across configured models through the AI gateway.

Prints per model: accuracy, grounding failures, mean/p95 latency, tokens and cost.
Live calls run ONLY when the provider's key is set; otherwise the model is reported SKIPPED.
Use --fake to exercise the harness offline with a deterministic fake provider (no network).

  python scripts/ai_benchmark.py                       # all models in the capability table that have a key
  python scripts/ai_benchmark.py --models anthropic:claude-haiku-4-5-20251001,openai:gpt-5.6
  python scripts/ai_benchmark.py --fake
Cost shows n/a unless a price is set (DRIFTGUARD_AI_PRICE_IN_PER_MTOK / _OUT_PER_MTOK or capability file).
"""
from __future__ import annotations
import argparse, json, os, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))
from driftguard_platform.ai import AIOperation, AIRequest, AIResult, registry  # noqa: E402
from driftguard_platform.ai_gateway import CapabilityTable, GatewayPolicy, AIGateway  # noqa: E402
from driftguard_platform.byoai import DEFAULT_SECRET_REFS, GatewayConfig, gateway_from_config  # noqa: E402
from driftguard_platform.secrets import create_secret_provider  # noqa: E402

CASES = ROOT / "backend" / "tests" / "fixtures" / "ai_benchmark" / "cases.json"


class FakeProvider:
    """Offline stand-in: answers each case correctly by reading the expectation back out of the prompt table."""
    name, model = "fake", "fake-1"
    def __init__(self, cases): self._by_content = {c["content"]: c for c in cases}
    def execute(self, request):
        c = self._by_content[request.content]
        data = {**c["expect"], "confidence": 0.9, "source_ids": list(request.source_ids)}
        return AIResult(request.operation, data, self.name, self.model, request.source_ids, 0.9, (),
                        {"input_tokens": 100, "output_tokens": 20}, request.correlation_id)


def run_model(label: str, gateway: AIGateway, cases: list[dict]) -> dict:
    ok = grounding = unavailable = 0
    lat: list[float] = []; tokens = 0; cost = 0.0; priced = True
    for c in cases:
        req = AIRequest(AIOperation(c["operation"]), c["content"], source_ids=tuple(c["source_ids"]))
        t0 = time.perf_counter()
        out = gateway.execute(req, assessment_id=f"bench-{label}")
        lat.append(time.perf_counter() - t0)
        tokens += out.tokens; cost += out.cost_usd
        if out.ok:
            got = {k: str(v).strip().lower() for k, v in out.result.data.items()}
            ok += all(got.get(k) == str(v).lower() for k, v in c["expect"].items())
        elif out.reason_code == "UNGROUNDED_OR_PROHIBITED_OUTPUT": grounding += 1
        else: unavailable += 1
    caps = gateway.capabilities.get(getattr(gateway.primary, "name", ""), getattr(gateway.primary, "model", ""))
    priced = bool(caps and caps.price_in_per_mtok is not None and caps.price_out_per_mtok is not None) or gateway.policy.price_in_per_mtok is not None
    return {"model": label, "n": len(cases), "accuracy": ok / len(cases), "grounding_failures": grounding, "unavailable": unavailable,
            "mean_latency_s": statistics.mean(lat), "p95_latency_s": sorted(lat)[max(0, int(round(0.95 * len(lat))) - 1)],
            "tokens": tokens, "cost_usd": cost if priced else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", help="comma list of provider:model; default = every model in the capability table")
    ap.add_argument("--fake", action="store_true", help="offline harness check with a fake provider")
    a = ap.parse_args()
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    table = CapabilityTable.load()
    rows, skipped = [], []
    if a.fake:
        gw = AIGateway(FakeProvider(cases), capabilities=CapabilityTable({"fake:fake-1": {"json_mode": True, "context_tokens": 100000}}))
        rows.append(run_model("fake:fake-1", gw, cases))
    else:
        secrets = create_secret_provider()
        for label in (a.models.split(",") if a.models else list(table.keys())):
            provider, _, model = label.partition(":")
            ref = DEFAULT_SECRET_REFS.get(provider)
            try: secrets.get(ref)
            except Exception: skipped.append(f"{label} (SKIPPED: {ref} not set; no live call made)"); continue
            gw = gateway_from_config(GatewayConfig(provider=provider, model=model, max_retries=1), registry, secrets, capabilities=table)
            rows.append(run_model(label, gw, cases))
    print(f"{'model':45} {'acc':>5} {'ground-fail':>11} {'unavail':>7} {'mean s':>7} {'p95 s':>6} {'tokens':>7} {'cost $':>8}")
    for r in rows:
        cost = "n/a" if r["cost_usd"] is None else f"{r['cost_usd']:.4f}"
        print(f"{r['model']:45} {r['accuracy']:5.0%} {r['grounding_failures']:11d} {r['unavailable']:7d} {r['mean_latency_s']:7.2f} {r['p95_latency_s']:6.2f} {r['tokens']:7d} {cost:>8}")
    for s in skipped: print(s)
    if not rows and not a.fake: print("No live calls were made (no provider keys configured).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
