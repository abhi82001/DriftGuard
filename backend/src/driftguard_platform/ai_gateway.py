"""AI gateway: one interface over the AI provider adapters (OpenAI, Anthropic, OpenRouter).

Wraps the existing AIProvider boundary in `ai.py`; adds capability pre-checks, retry with
backoff, optional fallback, a per-assessment token/cost cap and grounding enforcement.

Invariants:
  * The gateway never raises for a provider failure and never mutates anything: a failure
    becomes a GatewayOutcome with status AI_UNAVAILABLE. Deterministic results are untouched.
  * Output without valid source_ids, or carrying a verdict word, is rejected, never repaired.
  * Credentials are never logged; error text is scrubbed before it is recorded.
"""
from __future__ import annotations
import json, logging, os, re, threading, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from .ai import (AIOutputError, AIProvider, AIProviderError, AIRequest, AIResult, AIUnavailable, AIValidationError,
                 SEMANTIC_OPERATIONS, prohibited_scan_text, validate_result)

log = logging.getLogger("driftguard.ai")

STATUS_OK = "OK"
STATUS_UNAVAILABLE = "AI_UNAVAILABLE"
EXTRA_PROHIBITED = {"SOC2_PASSED", "SOC2_FAILED", "QUALIFIED_OPINION", "UNQUALIFIED_OPINION"}
CAPABILITIES_PATH = Path(__file__).with_name("ai_models.json")


# ---------------------------------------------------------------- typed errors
class AICompatibilityError(AIProviderError):
    """Raised before any call when the model cannot serve the request."""
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code

class AIBudgetExceeded(AIProviderError):
    """The per-assessment token or cost cap would be exceeded."""
    code = "BUDGET_EXCEEDED"


# ------------------------------------------------------------ capability table
@dataclass(frozen=True)
class ModelCapability:
    provider: str
    model: str
    json_mode: bool
    context_tokens: int
    tool_use: bool
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None

class CapabilityTable:
    def __init__(self, entries: Mapping[str, Mapping[str, Any]]):
        self._m: dict[str, ModelCapability] = {}
        for key, e in entries.items():
            provider, _, model = key.partition(":")
            self._m[key.lower()] = ModelCapability(provider, model, bool(e.get("json_mode")), int(e.get("context_tokens", 0)),
                                                   bool(e.get("tool_use")), e.get("price_in_per_mtok"), e.get("price_out_per_mtok"))
    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "CapabilityTable":
        p = Path(path or os.getenv("DRIFTGUARD_AI_CAPABILITIES_FILE") or CAPABILITIES_PATH)
        return cls(json.loads(p.read_text(encoding="utf-8"))["models"])
    def get(self, provider: str, model: str) -> ModelCapability | None:
        return self._m.get(f"{provider}:{model}".lower())
    def keys(self) -> tuple[str, ...]: return tuple(sorted(self._m))


def estimate_tokens(request: AIRequest) -> int:
    text = json.dumps({"c": request.content, "x": dict(request.context), "s": request.source_ids}, default=str)
    return len(text) // 3 + 1   # deliberately pessimistic; real usage replaces it after the call

def check_compatibility(cap: ModelCapability | None, provider: str, model: str, request: AIRequest, *,
                        max_output_tokens: int, need_price: bool = False,
                        price_in: float | None = None, price_out: float | None = None) -> ModelCapability:
    """Fail with a typed AICompatibilityError before any network call."""
    if cap is None:
        raise AICompatibilityError("UNKNOWN_MODEL", f"{provider}:{model} is not in the capability table")
    if not cap.json_mode:
        raise AICompatibilityError("NO_JSON_MODE", f"{provider}:{model} cannot return structured JSON")
    need = estimate_tokens(request) + max_output_tokens
    if need > cap.context_tokens:
        raise AICompatibilityError("CONTEXT_TOO_SMALL", f"request needs ~{need} tokens; {provider}:{model} allows {cap.context_tokens}")
    pin = price_in if price_in is not None else cap.price_in_per_mtok
    pout = price_out if price_out is not None else cap.price_out_per_mtok
    if need_price and (pin is None or pout is None):
        raise AICompatibilityError("PRICE_UNKNOWN", f"cost cap is set but {provider}:{model} has no configured price")
    return cap


# ----------------------------------------------------------------- usage / cap
def normalize_usage(usage: Mapping[str, Any] | None) -> tuple[int, int]:
    """(input_tokens, output_tokens) across Responses, chat-completions and Messages shapes."""
    u = dict(usage or {})
    i = u.get("input_tokens", u.get("prompt_tokens", 0)) or 0
    o = u.get("output_tokens", u.get("completion_tokens", 0)) or 0
    return int(i), int(o)

@dataclass
class AssessmentUsage:
    tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

class UsageLedger:
    """Per-assessment token/cost accounting. In-memory; thread-safe."""
    def __init__(self) -> None:
        self._u: dict[str, AssessmentUsage] = {}
        self._lock = threading.Lock()
    def get(self, assessment_id: str) -> AssessmentUsage:
        with self._lock:
            u = self._u.get(assessment_id, AssessmentUsage())
            return AssessmentUsage(u.tokens, u.cost_usd, u.calls)
    def add(self, assessment_id: str, tokens: int, cost: float) -> None:
        with self._lock:
            u = self._u.setdefault(assessment_id, AssessmentUsage())
            u.tokens += tokens; u.cost_usd += cost; u.calls += 1


# -------------------------------------------------------------------- grounding
def ground_result(request: AIRequest, result: AIResult) -> AIResult:
    """Reject ungrounded output or output carrying a verdict word. Never repairs."""
    validate_result(result)   # confidence range, PROHIBITED verdicts, non-empty source_ids
    blob = prohibited_scan_text(result)   # whole payload; closed-vocabulary fields only for semantic operations
    for banned in EXTRA_PROHIBITED:
        if banned in blob:
            raise AIValidationError(f"AI result contains a prohibited verdict: {banned}")
    allowed = set(request.source_ids)
    if not allowed:
        raise AIValidationError("grounded AI operations require source_ids on the request")
    cited = set(result.source_ids)
    if not cited or not cited <= allowed:
        raise AIValidationError("AI result cites source_ids that were not supplied")
    model_cited = result.data.get("source_ids")
    if model_cited is not None:
        if not isinstance(model_cited, (list, tuple)) or not model_cited or not all(isinstance(s, str) for s in model_cited) \
                or not set(model_cited) <= allowed:
            raise AIValidationError("model output carries missing or unknown source_ids")
    return result


# ---------------------------------------------------------------------- outcome
@dataclass(frozen=True)
class GatewayOutcome:
    status: str
    result: AIResult | None = None
    reason_code: str = ""
    detail: str = ""
    provider: str = ""
    model: str = ""
    attempts: int = 0
    fallback_used: bool = False
    tokens: int = 0
    cost_usd: float = 0.0
    @property
    def ok(self) -> bool: return self.status == STATUS_OK
    def as_record(self) -> dict:
        """Persistable record. An unavailable outcome states that deterministic results are unaffected."""
        rec = {"status": "AI unavailable" if not self.ok else "ok", "reason_code": self.reason_code, "detail": self.detail,
               "provider": self.provider, "model": self.model, "attempts": self.attempts,
               "fallback_used": self.fallback_used, "tokens": self.tokens, "cost_usd": round(self.cost_usd, 6)}
        if not self.ok: rec["deterministic_results_affected"] = False
        return rec


@dataclass(frozen=True)
class GatewayPolicy:
    max_retries: int = 2
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0
    total_deadline_s: float = 60.0
    max_output_tokens: int = 2048
    token_cap: int | None = None
    cost_cap_usd: float | None = None
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None
    semantic_token_cap: int | None = None   # separate per-assessment budget for semantic evaluation/extraction


_KEY_LIKE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+)")

class AIGateway:
    def __init__(self, primary: AIProvider, fallback: AIProvider | None = None, *, capabilities: CapabilityTable | None = None,
                 policy: GatewayPolicy | None = None, ledger: UsageLedger | None = None, secrets: Iterable[str] = (),
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.primary, self.fallback = primary, fallback
        self.capabilities = capabilities or CapabilityTable.load()
        self.policy = policy or GatewayPolicy()
        self.ledger = ledger or UsageLedger()
        self._secrets = tuple(s for s in secrets if s)
        self._sleep, self._clock = sleep, clock

    def scrub(self, text: str) -> str:
        for s in self._secrets: text = text.replace(s, "[redacted]")
        return _KEY_LIKE.sub("[redacted]", text)[:300]

    def execute(self, request: AIRequest, assessment_id: str = "default") -> GatewayOutcome:
        """Never raises for provider/compat/budget failures; returns AI_UNAVAILABLE instead."""
        last: GatewayOutcome | None = None
        for idx, provider in enumerate([p for p in (self.primary, self.fallback) if p is not None]):
            out = self._run_provider(provider, request, assessment_id, fallback_used=idx == 1)
            if out.ok: return out
            last = out
            if out.reason_code == "BUDGET_EXCEEDED": break   # a different provider shares the same cap
        log.warning("AI unavailable: %s (%s)", last.reason_code, last.provider)
        return last

    def _run_provider(self, provider: AIProvider, request: AIRequest, aid: str, fallback_used: bool) -> GatewayOutcome:
        pname = getattr(provider, "name", "unknown"); model = getattr(provider, "model", "") or ""
        pol = self.policy
        out_tokens = request.max_output_tokens or pol.max_output_tokens
        if request.operation in SEMANTIC_OPERATIONS:   # many calls per assessment: own ledger scope and cap
            aid, token_cap = f"{aid}#semantic", pol.semantic_token_cap
        else:
            token_cap = pol.token_cap
        def fail(code: str, exc: BaseException | str, attempts: int = 0) -> GatewayOutcome:
            return GatewayOutcome(STATUS_UNAVAILABLE, None, code, self.scrub(f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else exc),
                                  pname, model, attempts, fallback_used)
        if pname == "disabled":
            return fail("AI_DISABLED", "AI is disabled; deterministic processing is unaffected")
        cap = self.capabilities.get(pname, model)
        try:
            check_compatibility(cap, pname, model, request, max_output_tokens=out_tokens,
                                need_price=pol.cost_cap_usd is not None, price_in=pol.price_in_per_mtok, price_out=pol.price_out_per_mtok)
            self._check_budget(aid, estimate_tokens(request) + out_tokens, cap, token_cap)
        except AICompatibilityError as exc: return fail(exc.code, exc)
        except AIBudgetExceeded as exc: return fail("BUDGET_EXCEEDED", exc)
        started, attempts = self._clock(), 0
        while True:
            attempts += 1
            try:
                result = provider.execute(request)
                tokens, cost = self._account(aid, result, request, cap, out_tokens)
                ground_result(request, result)   # usage is charged even if the output is then rejected
                return GatewayOutcome(STATUS_OK, result, "", "", pname, model, attempts, fallback_used, tokens, cost)
            except AIUnavailable as exc: return fail("PROVIDER_UNAVAILABLE", exc, attempts)
            except AIValidationError as exc: return fail("UNGROUNDED_OR_PROHIBITED_OUTPUT", exc, attempts)
            except AIOutputError as exc: return fail("UNUSABLE_OUTPUT", exc, attempts)   # not retried, never repaired
            except (AIProviderError, TimeoutError, ConnectionError) as exc:
                delay = min(pol.backoff_max_s, pol.backoff_base_s * (2 ** (attempts - 1)))
                if attempts > pol.max_retries or self._clock() - started + delay > pol.total_deadline_s:
                    return fail("TIMEOUT" if isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__ + str(exc) else "PROVIDER_ERROR", exc, attempts)
                try: self._check_budget(aid, estimate_tokens(request) + out_tokens, cap, token_cap)
                except AIBudgetExceeded as b: return fail("BUDGET_EXCEEDED", b, attempts)
                self._sleep(delay)
            except Exception as exc:   # an adapter bug must still not touch deterministic results
                return fail("PROVIDER_ERROR", exc, attempts)

    def _price(self, cap: ModelCapability | None) -> tuple[float | None, float | None]:
        pol = self.policy
        return (pol.price_in_per_mtok if pol.price_in_per_mtok is not None else (cap.price_in_per_mtok if cap else None),
                pol.price_out_per_mtok if pol.price_out_per_mtok is not None else (cap.price_out_per_mtok if cap else None))

    def _check_budget(self, aid: str, projected_tokens: int, cap: ModelCapability | None, token_cap: int | None = None) -> None:
        pol, used = self.policy, self.ledger.get(aid)
        if token_cap is not None and used.tokens + projected_tokens > token_cap:
            raise AIBudgetExceeded(f"token cap {token_cap} would be exceeded ({used.tokens} used)")
        if pol.cost_cap_usd is not None:
            pin, pout = self._price(cap)
            projected = (projected_tokens * max(pin or 0, pout or 0)) / 1e6   # upper bound: every token at the higher rate
            if used.cost_usd + projected > pol.cost_cap_usd:
                raise AIBudgetExceeded(f"cost cap ${pol.cost_cap_usd} would be exceeded (${used.cost_usd:.4f} used)")

    def _account(self, aid: str, result: AIResult, request: AIRequest, cap: ModelCapability | None, out_tokens: int | None = None) -> tuple[int, float]:
        tin, tout = normalize_usage(result.usage)
        if not (tin or tout):   # provider reported nothing: charge the pessimistic estimate rather than zero
            tin, tout = estimate_tokens(request), out_tokens or self.policy.max_output_tokens
        pin, pout = self._price(cap)
        cost = (tin * (pin or 0) + tout * (pout or 0)) / 1e6
        self.ledger.add(aid, tin + tout, cost)
        return tin + tout, cost
