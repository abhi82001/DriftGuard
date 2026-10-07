from __future__ import annotations
from typing import Protocol, runtime_checkable


class SecretError(RuntimeError):
    pass


@runtime_checkable
class SecretProvider(Protocol):
    name: str
    def get(self, reference: str) -> str: ...
