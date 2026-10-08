"""CP017 limits for grounded semantic evidence extraction. Provider/model/key come from the unified AI config (DRIFTGUARD_AI_*)."""
from __future__ import annotations
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class SemanticRuntimeConfig:
    provider: str = ""
    model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 1
    max_tokens: int = 1800
    max_segments: int = 80
    max_segment_chars: int = 12000

    @classmethod
    def from_env(cls):
        def _int(name, default, lo, hi):
            try: value=int(os.getenv(name,str(default)))
            except ValueError: value=default
            return max(lo,min(hi,value))
        def _float(name, default, lo, hi):
            try: value=float(os.getenv(name,str(default)))
            except ValueError: value=default
            return max(lo,min(hi,value))
        from driftguard_platform.byoai import resolve_provider_and_model
        provider,model,_legacy=resolve_provider_and_model()
        return cls(
            provider="" if provider=="disabled" else provider,
            model=model,
            timeout_seconds=_float("DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS",30,5,120),
            max_retries=_int("DRIFTGUARD_SEMANTIC_MAX_RETRIES",1,0,3),
            max_tokens=_int("DRIFTGUARD_SEMANTIC_MAX_TOKENS",1800,256,4096),
            max_segments=_int("DRIFTGUARD_SEMANTIC_MAX_SEGMENTS",80,1,500),
            max_segment_chars=_int("DRIFTGUARD_SEMANTIC_MAX_SEGMENT_CHARS",12000,1000,30000),
        )

    def readiness(self):
        """Delegates to the unified AI path: DRIFTGUARD_AI_PROVIDER / DRIFTGUARD_AI_MODEL / provider key."""
        from driftguard_platform.ai_runtime import readiness
        r=readiness()
        if r["ready"]:
            return True,"SEMANTIC_ACTIVE",f"configured {r['provider']} provider"
        return False,"SEMANTIC_UNAVAILABLE",r["reason"]
