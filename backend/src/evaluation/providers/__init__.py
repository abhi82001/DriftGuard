"""Concrete SemanticEvaluator providers.

Each module here adapts one external model provider to the
provider-independent SemanticEvaluator contract (Checkpoint 003) and is run
through the Checkpoint 004 execution layer. Provider output is untrusted until
validate_semantic_result() succeeds.

Importing this package does NOT import any provider SDK: each adapter imports
its SDK lazily, only when it has to build a real client.
"""

from .claude import (
    ClaudeOutputError,
    ClaudeProviderError,
    ClaudeSemanticEvaluator,
)

__all__ = [
    "ClaudeOutputError",
    "ClaudeProviderError",
    "ClaudeSemanticEvaluator",
]
