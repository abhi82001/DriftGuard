from __future__ import annotations
from collections.abc import Callable
from .contracts import SecretProvider, SecretError


class SecretRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., SecretProvider]] = {}
    def register(self, name: str, factory: Callable[..., SecretProvider]) -> None:
        self._factories[name.strip().lower()] = factory
    def create(self, name: str, **kwargs) -> SecretProvider:
        key = name.strip().lower()
        if key not in self._factories:
            raise SecretError(f"unsupported secret provider: {key}")
        return self._factories[key](**kwargs)
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

registry = SecretRegistry()
