from __future__ import annotations
from collections.abc import Callable
from .accounts import AccountRepository
from .contracts import UnsupportedStorageProvider
from .providers.sqlite_accounts import SQLiteAccountRepository
from . import create_storage
from driftguard_platform.config import PlatformConfig


class RepositoryRegistry:
    def __init__(self): self._accounts: dict[str, Callable[..., AccountRepository]] = {}
    def register_accounts(self, name: str, factory: Callable[..., AccountRepository]) -> None:
        self._accounts[name.strip().lower()] = factory
    def create_accounts(self, config: PlatformConfig | None = None) -> AccountRepository:
        cfg = config or PlatformConfig.from_env()
        if cfg.storage_provider not in self._accounts:
            raise UnsupportedStorageProvider(f"no account repository adapter for storage provider: {cfg.storage_provider}")
        return self._accounts[cfg.storage_provider](create_storage(cfg))
    def account_providers(self) -> tuple[str, ...]: return tuple(sorted(self._accounts))

registry = RepositoryRegistry()
registry.register_accounts("sqlite", lambda storage: SQLiteAccountRepository(storage))

def create_account_repository(config: PlatformConfig | None = None) -> AccountRepository:
    return registry.create_accounts(config)
