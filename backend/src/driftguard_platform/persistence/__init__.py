from __future__ import annotations

from pathlib import Path
from typing import Any

from driftguard_platform.config import PlatformConfig
from .contracts import StorageProvider, StorageError, UnsupportedStorageProvider
from .registry import StorageRegistry, registry
from .providers.sqlite import SQLiteStorageProvider

registry.register("sqlite", lambda **kw: SQLiteStorageProvider(kw.get("database_url", "")))


def create_storage(config: PlatformConfig | None = None, **kwargs: Any) -> StorageProvider:
    cfg = config or PlatformConfig.from_env()
    database_url = kwargs.pop("database_url", None) or cfg.storage_url
    if cfg.storage_provider == "sqlite" and not database_url:
        database_url = str(Path(__file__).resolve().parents[3] / "driftguard.db")
    return registry.create(cfg.storage_provider, database_url=database_url, **kwargs)

__all__ = ["StorageProvider", "StorageError", "UnsupportedStorageProvider", "StorageRegistry", "registry", "create_storage"]

# Application repositories are imported lazily by callers to avoid registry cycles.
