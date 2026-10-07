from __future__ import annotations

from typing import Any, ContextManager, Protocol, runtime_checkable


class StorageError(RuntimeError):
    pass


class UnsupportedStorageProvider(StorageError):
    pass


@runtime_checkable
class StorageProvider(Protocol):
    """Small infrastructure boundary used by DriftGuard application repositories.

    `connection` deliberately exposes a DB-API compatible transaction today so the
    existing application can migrate incrementally without rewriting domain logic.
    Provider-specific SQL must stay in repositories/providers, never compliance code.
    """

    name: str

    def initialize(self) -> None: ...
    def connect(self) -> Any: ...
    def connection(self) -> ContextManager[Any]: ...
    def healthcheck(self) -> bool: ...
