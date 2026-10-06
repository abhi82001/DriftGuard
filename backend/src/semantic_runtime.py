"""CP017 production guardrails for grounded semantic evidence extraction."""
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
        return cls(
            provider=os.getenv("DRIFTGUARD_SEMANTIC_PROVIDER","").strip().lower(),
            model=os.getenv("DRIFTGUARD_CLAUDE_MODEL","").strip(),
            timeout_seconds=_float("DRIFTGUARD_SEMANTIC_TIMEOUT_SECONDS",30,5,120),
            max_retries=_int("DRIFTGUARD_SEMANTIC_MAX_RETRIES",1,0,3),
            max_tokens=_int("DRIFTGUARD_SEMANTIC_MAX_TOKENS",1800,256,4096),
            max_segments=_int("DRIFTGUARD_SEMANTIC_MAX_SEGMENTS",80,1,500),
            max_segment_chars=_int("DRIFTGUARD_SEMANTIC_MAX_SEGMENT_CHARS",12000,1000,30000),
        )

    def readiness(self):
        if not self.provider:
            return False,"SEMANTIC_UNAVAILABLE","provider not configured"
        if self.provider != "claude":
            return False,"SEMANTIC_UNAVAILABLE",f"unsupported provider: {self.provider}"
        if not self.model:
            return False,"SEMANTIC_UNAVAILABLE","DRIFTGUARD_CLAUDE_MODEL is not configured"
        if not os.getenv("ANTHROPIC_API_KEY","").strip():
            return False,"SEMANTIC_UNAVAILABLE","ANTHROPIC_API_KEY is not configured"
        try:
            import anthropic  # noqa:F401
        except ImportError:
            return False,"SEMANTIC_UNAVAILABLE","anthropic SDK is not installed"
        return True,"SEMANTIC_ACTIVE","configured real Claude provider"
