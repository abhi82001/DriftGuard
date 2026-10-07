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
