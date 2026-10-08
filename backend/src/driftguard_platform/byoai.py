from __future__ import annotations
from dataclasses import dataclass
from .ai import AIRegistry, AIProvider
@dataclass(frozen=True)
class TenantAIConfig:
    tenant_id:str; provider:str="disabled"; model:str=""; endpoint:str=""; enabled_capabilities:frozenset[str]=frozenset(); redact:bool=True; max_excerpt_chars:int=12000

def provider_for(config:TenantAIConfig, registry:AIRegistry, **secrets)->AIProvider:
    if config.provider=="disabled": return registry.create("disabled")
    kwargs=dict(secrets)
    if config.model: kwargs["model"]=config.model
    return registry.create(config.provider,**kwargs)

@dataclass(frozen=True)
class AIProviderConfig:
    """Provider selection with secret references suitable for persisted tenant config."""
    provider: str = "disabled"
    model: str = ""
    secret_refs: dict[str, str] | None = None


def provider_from_references(config: AIProviderConfig, registry: AIRegistry, secret_provider) -> AIProvider:
    secrets = {name: secret_provider.get(ref) for name, ref in (config.secret_refs or {}).items()}
    if config.model:
        secrets["model"] = config.model
    return registry.create(config.provider, **secrets)


# ---- gateway configuration (internal only: env or config file; never exposed to customers) ----
import json as _json, os as _os
from pathlib import Path as _Path

DEFAULT_SECRET_REFS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
DEFAULT_TOKEN_CAP = 20000
DEFAULT_SEMANTIC_TOKEN_CAP = 500000
_FORBIDDEN_FILE_KEYS ={"api_key", "key", "secret", "token", "password"}


LEGACY_ENV = ("DRIFTGUARD_SEMANTIC_PROVIDER", "DRIFTGUARD_CLAUDE_MODEL", "DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS", "DRIFTGUARD_SEMANTIC_MAX_RETRIES")   # deprecated fallbacks, removed after one release
_legacy_warned = False


def resolve_provider_and_model() -> tuple[str, str, list[str]]:
    """(provider, model, deprecated env vars that decided the result). DRIFTGUARD_AI_* always wins;
    the old Claude-only variables apply only where the new one is unset. An explicit
    DRIFTGUARD_AI_PROVIDER=disabled is respected."""
    e = lambda n: _os.getenv(n, "").strip()
    used: list[str] = []
    provider, model = e("DRIFTGUARD_AI_PROVIDER").lower(), e("DRIFTGUARD_AI_MODEL")
    if not provider and e("DRIFTGUARD_SEMANTIC_PROVIDER").lower() == "claude":
        provider = "anthropic"; used.append("DRIFTGUARD_SEMANTIC_PROVIDER")
    if not model and provider == "anthropic" and e("DRIFTGUARD_CLAUDE_MODEL"):
        model = e("DRIFTGUARD_CLAUDE_MODEL"); used.append("DRIFTGUARD_CLAUDE_MODEL")
    return provider or "disabled", model, used


def _warn_legacy_once(names: list[str]) -> None:
    global _legacy_warned
    if _legacy_warned:
        return
    _legacy_warned = True
    import logging, warnings
    msg = (f"{', '.join(names)} is deprecated and will be removed after one release; "
           "use DRIFTGUARD_AI_PROVIDER and DRIFTGUARD_AI_MODEL")
    logging.getLogger("driftguard.ai").warning(msg)
    warnings.warn(msg, DeprecationWarning, stacklevel=3)


@dataclass(frozen=True)
class GatewayConfig:
    """Provider/model switching by config only. Secrets are references, never values."""
    provider: str = "disabled"
    model: str = ""
    fallback_provider: str = ""
    fallback_model: str = ""
    secret_refs: dict[str, str] | None = None     # provider -> secret reference (env var name for the env provider)
    timeout_s: float = 30.0
    max_retries: int = 2
    backoff_base_s: float = 0.5
    token_cap: int | None = None
    cost_cap_usd: float | None = None
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None
    semantic_token_cap: int | None = DEFAULT_SEMANTIC_TOKEN_CAP

    @classmethod
    def from_mapping(cls, d: dict) -> "GatewayConfig":
        bad = sorted(k for k in d if k.lower() in _FORBIDDEN_FILE_KEYS)
        if bad:
            raise ValueError(f"AI config must reference secrets via secret_refs, not hold them: {bad}")
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(f"unknown AI config field(s): {unknown}")
        return cls(**d)

    @classmethod
    def from_file(cls, path: str) -> "GatewayConfig":
        return cls.from_mapping(_json.loads(_Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        path = _os.getenv("DRIFTGUARD_AI_CONFIG_FILE", "").strip()
        if path:
            return cls.from_file(path)
        def num(name, conv):
            v = _os.getenv(name, "").strip()
            return conv(v) if v else None
        e = lambda n, d="": _os.getenv(n, d).strip()
        provider, model, legacy = resolve_provider_and_model()
        timeout_s = num("DRIFTGUARD_AI_TIMEOUT_S", float)
        if timeout_s is None and num("DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS", float):
            timeout_s = num("DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS", float)
            legacy.append("DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS")
        retries = num("DRIFTGUARD_AI_MAX_RETRIES", int)
        if retries is None and e("DRIFTGUARD_SEMANTIC_MAX_RETRIES"):
            retries = num("DRIFTGUARD_SEMANTIC_MAX_RETRIES", int)
            legacy.append("DRIFTGUARD_SEMANTIC_MAX_RETRIES")
        if legacy:
            _warn_legacy_once(legacy)
        return cls(provider=provider, model=model,
                   fallback_provider=e("DRIFTGUARD_AI_FALLBACK_PROVIDER").lower(), fallback_model=e("DRIFTGUARD_AI_FALLBACK_MODEL"),
                   timeout_s=timeout_s or 30.0, max_retries=retries if retries is not None else 2,
                   token_cap=num("DRIFTGUARD_AI_TOKEN_CAP", int) or DEFAULT_TOKEN_CAP, cost_cap_usd=num("DRIFTGUARD_AI_COST_CAP_USD", float),
                   price_in_per_mtok=num("DRIFTGUARD_AI_PRICE_IN_PER_MTOK", float), price_out_per_mtok=num("DRIFTGUARD_AI_PRICE_OUT_PER_MTOK", float),
                   semantic_token_cap=num("DRIFTGUARD_AI_SEMANTIC_TOKEN_CAP", int) or DEFAULT_SEMANTIC_TOKEN_CAP)


def _build_provider(name: str, model: str, config: GatewayConfig, registry: AIRegistry, secret_provider):
    if name in ("", "disabled"):
        return registry.create("disabled"), ()
    ref = (config.secret_refs or {}).get(name) or DEFAULT_SECRET_REFS.get(name)
    kwargs: dict = {"timeout": config.timeout_s}
    secrets: tuple[str, ...] = ()
    if ref and secret_provider is not None:
        try:
            key = secret_provider.get(ref)
            kwargs["api_key"], secrets = key, (key,)
        except Exception:   # missing secret: the adapter reports AIUnavailable at call time
            pass
    if model:
        kwargs["model"] = model
    return registry.create(name, **kwargs), secrets


def gateway_from_config(config: GatewayConfig, registry: AIRegistry, secret_provider=None, *, capabilities=None, ledger=None, **gw_kwargs):
    """Build an AIGateway purely from config. Switching provider/model is a config change."""
    from .ai_gateway import AIGateway, GatewayPolicy
    primary, s1 = _build_provider(config.provider, config.model, config, registry, secret_provider)
    fallback, s2 = (None, ())
    if config.fallback_provider and config.fallback_provider != "disabled":
        fallback, s2 = _build_provider(config.fallback_provider, config.fallback_model, config, registry, secret_provider)
    policy = GatewayPolicy(max_retries=config.max_retries, backoff_base_s=config.backoff_base_s, token_cap=config.token_cap,
                           cost_cap_usd=config.cost_cap_usd, price_in_per_mtok=config.price_in_per_mtok, price_out_per_mtok=config.price_out_per_mtok,
                           semantic_token_cap=config.semantic_token_cap)
    return AIGateway(primary, fallback, capabilities=capabilities, policy=policy, ledger=ledger, secrets=s1 + s2, **gw_kwargs)
