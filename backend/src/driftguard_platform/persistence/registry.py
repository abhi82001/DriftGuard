from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contracts import StorageProvider, UnsupportedStorageProvider


class StorageRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., StorageProvider]] = {}

    def register(self, name: str, factory: Callable[..., StorageProvider]) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("storage provider name is required")
        self._factories[key] = factory

    def create(self, name: str, **kwargs: Any) -> StorageProvider:
        key = name.strip().lower()
        try:
            factory = self._factories[key]
        except KeyError as exc:
            raise UnsupportedStorageProvider(f"unsupported storage provider: {key}") from exc
        return factory(**kwargs)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


registry = StorageRegistry()
