from __future__ import annotations
import os
from .contracts import SecretError


class EnvironmentSecretProvider:
    """Development/default adapter. References are environment variable names."""
    name = "env"
    def get(self, reference: str) -> str:
        if not reference or reference not in os.environ:
            raise SecretError(f"secret reference is not configured: {reference}")
        return os.environ[reference]
