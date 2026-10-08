"""Process-wide AIGateway access for AI call sites.

Call sites use `run_ai` / `run_with` and get a GatewayOutcome; any setup or provider failure
becomes an AI_UNAVAILABLE outcome, never an exception, so deterministic results are untouched.
"""
from __future__ import annotations
import threading
from .ai import AIOutputError, AIProviderError, AIRequest, AIResult, validate_result, registry
from .ai_gateway import AIGateway, GatewayOutcome, STATUS_OK, STATUS_UNAVAILABLE

_gateway: AIGateway | None = None
_lock = threading.Lock()


def get_gateway() -> AIGateway:
    """Gateway built from GatewayConfig.from_env; cached until reset_gateway()."""
    global _gateway
    with _lock:
        if _gateway is None:
            from .byoai import GatewayConfig, gateway_from_config
            try:
                from .secrets import create_secret_provider
                secrets = create_secret_provider()
            except Exception:   # no secret store: adapters report AIUnavailable at call time
                secrets = None
            _gateway = gateway_from_config(GatewayConfig.from_env(), registry, secrets)
        return _gateway


def reset_gateway() -> None:
    global _gateway
    with _lock:
        _gateway = None


def _unavailable(code: str, exc: BaseException) -> GatewayOutcome:
    return GatewayOutcome(STATUS_UNAVAILABLE, None, code, f"{type(exc).__name__}: {str(exc)[:200]}")


def run_ai(request: AIRequest, gateway: AIGateway | None = None, assessment_id: str = "default") -> GatewayOutcome:
    """Execute through the gateway. Never raises."""
    try:
        return (gateway or get_gateway()).execute(request, assessment_id)
    except Exception as exc:
        return _unavailable("AI_SETUP_FAILED", exc)


def run_with(target, request: AIRequest, assessment_id: str = "default") -> GatewayOutcome:
    """`target` may be None (process gateway), an AIGateway, or a bare AIProvider.
    A bare provider is called directly but its result is still validated (verdicts, confidence, source_ids)."""
    if target is None or isinstance(target, AIGateway):
        return run_ai(request, target, assessment_id)
    try:
        result: AIResult = validate_result(target.execute(request))
    except AIOutputError as exc:
        return _unavailable("UNUSABLE_OUTPUT", exc)
    except AIProviderError as exc:
        return _unavailable("PROVIDER_ERROR", exc)
    except Exception as exc:
        return _unavailable("PROVIDER_ERROR", exc)
    return GatewayOutcome(STATUS_OK, result, provider=getattr(target, "name", ""), model=getattr(target, "model", "") or "", attempts=1)


def readiness() -> dict:
    """Is the unified AI path usable? Config, key and SDK checks only; no network call and no key value is returned.
    {"ready", "provider", "model", "missing" (env var names), "reason", "deprecated_env_in_use"}"""
    import importlib.util
    from .byoai import DEFAULT_SECRET_REFS, GatewayConfig, resolve_provider_and_model
    from .ai_gateway import CapabilityTable
    _, _, legacy = resolve_provider_and_model()
    out = {"ready": False, "provider": "disabled", "model": "", "missing": [], "reason": "", "deprecated_env_in_use": legacy}
    try:
        cfg = GatewayConfig.from_env()
    except Exception as exc:   # unreadable config file etc.
        out["reason"] = f"AI config invalid: {type(exc).__name__}"
        return out
    out["provider"], out["model"] = cfg.provider, cfg.model
    if cfg.provider in ("", "disabled"):
        out["missing"] = ["DRIFTGUARD_AI_PROVIDER"] + ([] if cfg.model else ["DRIFTGUARD_AI_MODEL"])
        out["reason"] = "AI provider not configured"
        return out
    if cfg.provider not in registry._factories:
        out["reason"] = f"unsupported provider: {cfg.provider}"
        return out
    if not cfg.model:
        out["missing"].append("DRIFTGUARD_AI_MODEL")
    ref = (cfg.secret_refs or {}).get(cfg.provider) or DEFAULT_SECRET_REFS.get(cfg.provider)
    try:
        from .secrets import create_secret_provider
        create_secret_provider().get(ref)
    except Exception:
        out["missing"].append(ref or f"{cfg.provider.upper()}_API_KEY")
    if out["missing"]:
        out["reason"] = "missing configuration"
        return out
    try:
        if CapabilityTable.load().get(cfg.provider, cfg.model) is None:
            out["reason"] = f"{cfg.provider}:{cfg.model} is not in the AI capability table"
            return out
    except Exception as exc:
        out["reason"] = f"capability table unreadable: {type(exc).__name__}"
        return out
    sdk = "anthropic" if cfg.provider == "anthropic" else "openai"
    if importlib.util.find_spec(sdk) is None:
        out["reason"] = f"{sdk} SDK is not installed"
        return out
    out["ready"], out["reason"] = True, "configured"
    return out
