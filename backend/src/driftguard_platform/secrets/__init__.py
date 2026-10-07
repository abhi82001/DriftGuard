from __future__ import annotations
from driftguard_platform.config import PlatformConfig
from .contracts import SecretProvider, SecretError
from .registry import SecretRegistry, registry
from .providers import EnvironmentSecretProvider

registry.register("env", lambda **_: EnvironmentSecretProvider())

def create_secret_provider(config: PlatformConfig | None = None) -> SecretProvider:
    cfg = config or PlatformConfig.from_env()
    return registry.create(cfg.secret_provider)

__all__ = ["SecretProvider", "SecretError", "SecretRegistry", "registry", "create_secret_provider"]
