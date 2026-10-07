from __future__ import annotations

from dataclasses import dataclass
import os


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class PlatformConfig:
    """Infrastructure selection only; domain/compliance behavior never belongs here."""

    storage_provider: str = "sqlite"
    storage_url: str = ""
    secret_provider: str = "env"
    ai_provider: str = "disabled"

    @classmethod
    def from_env(cls) -> "PlatformConfig":
        return cls(
            storage_provider=_env("DRIFTGUARD_STORAGE_PROVIDER", "sqlite").lower(),
            storage_url=_env("DRIFTGUARD_DATABASE_URL") or _env("DRIFTGUARD_DB"),
            secret_provider=_env("DRIFTGUARD_SECRET_PROVIDER", "env").lower(),
            ai_provider=_env("DRIFTGUARD_AI_PROVIDER", "disabled").lower(),
        )
