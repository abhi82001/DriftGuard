#!/usr/bin/env python3
"""Claude semantic evaluator adapter (Checkpoint 005).

One isolated concrete implementation of the Checkpoint 003 SemanticEvaluator
contract, backed by the official Anthropic Python SDK. It is plugged in through
the Checkpoint 004 execution layer and changes nothing about the flow:

    build_semantic_request -> ClaudeSemanticEvaluator.evaluate(request)
        -> UNTRUSTED provider output -> validate_semantic_result -> result

What this adapter does:
  * converts ONLY the supplied SemanticEvaluationRequest into the prompt (never
    the knowledge base: no controls, policies, mappings, other conditions, or
    other findings are sent);
  * instructs Claude that the supplied condition and expected elements are the
    sole authority, that it must not import outside SOC 2 requirements, invent
    findings/elements, or state any compliance conclusion;
  * requests machine-readable structured output (output_config.format) and
    parses it strictly into a SemanticEvaluationResult;
  * fails closed on a provider exception, an empty/truncated/refused response,
    malformed JSON, an unexpected key set, or a wrong field type.

What this adapter deliberately does NOT do:
  * repair, coerce, normalise, or default any value the model returned;
  * check vocabularies, ranges, element grounding, or finding authorization -
    that is validate_semantic_result()'s job (Checkpoint 003) and is not
    duplicated here;
  * retry, fall back to another provider, cache, or persist anything.

Transport is the unified AI gateway (driftguard_platform.ai_runtime). Configuration is
DRIFTGUARD_AI_PROVIDER, DRIFTGUARD_AI_MODEL and the provider key; DRIFTGUARD_CLAUDE_MODEL is
a deprecated fallback. ClaudeSemanticEvaluator remains as a thin wrapper.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from ..semantic import (
    REASON_CODES,
    SemanticError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticVerdict,
)

ENV_API_KEY = "ANTHROPIC_API_KEY"
ENV_MODEL = "DRIFTGUARD_CLAUDE_MODEL"   # DEPRECATED fallback; DRIFTGUARD_AI_MODEL is the configuration
DEFAULT_MAX_TOKENS = 4096


# --------------------------------------------------------------------- errors
class ClaudeProviderError(SemanticError):
    """The provider call itself could not be completed."""


class ClaudeOutputError(ClaudeProviderError):
    """The provider responded, but the response is unusable as a result.

    Empty, truncated, refused, not JSON, not an object, missing or carrying
    unexpected keys, or a field of the wrong type. Never repaired.
    """


# ------------------------------------------------------- structured contract
# Field names and vocabularies are derived from the existing Checkpoint 003
# definitions; nothing new is invented here.
_VERDICTS = sorted(v.value for v in SemanticVerdict)
_REASON_CODES = sorted(REASON_CODES)

_REQUIRED_FIELDS = (
    "assessment",
    "confidence",
    "present_elements",
    "missing_elements",
    "reason_codes",
    "needs_human_review",
)
_OPTIONAL_FIELDS = ("indicates_finding", "notes")

# Asks the provider for machine-readable output. This constrains the shape of
# the reply; it does not validate grounding or authorization.
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "assessment": {"type": "string", "enum": _VERDICTS},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "present_elements": {"type": "array", "items": {"type": "string"}},
        "missing_elements": {"type": "array", "items": {"type": "string"}},
        "reason_codes": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "enum": _REASON_CODES},
        },
        "needs_human_review": {"type": "boolean"},
        "indicates_finding": {"type": ["string", "null"]},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": list(_REQUIRED_FIELDS),
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You judge whether one questionnaire answer evidences the expected elements "
    "of one supplied condition. The supplied condition, expected elements and "
    "finding id are the ONLY authority.\n"
    "Rules:\n"
    "1. Evaluate only the supplied condition and its expected_elements.\n"
    "2. Do not use any outside SOC 2 requirement, control, criterion, policy or "
    "framework knowledge.\n"
    "3. Do not invent findings, element ids, reason codes or verdicts. Use only "
    "the supplied element ids, the supplied indicates_finding value (or null), "
    "and the enumerated vocabularies.\n"
    "4. Never state or imply SOC 2 compliance, non-compliance, pass, fail, "
    "certification or an audit opinion. You report evidence coverage only.\n"
    "5. An element is present only if the answer text itself evidences it; "
    "otherwise it is missing. Do not assume unstated practice.\n"
    "6. Return only the required structured fields, and nothing else."
)


# ------------------------------------------------------------------- adapter
class GatewaySemanticEvaluator:
    """SemanticEvaluator that runs through the AI gateway (ai_runtime.run_with).

    Only transport lives in the gateway: provider selection, retries, budget, structured output.
    Everything this module's header promises still holds: the request is the only content sent,
    output stays untrusted, `_to_result` maps it strictly without repair, and
    validate_semantic_result() remains the single judge of vocabularies, grounding and verdicts.

    `target` is None (process gateway built from DRIFTGUARD_AI_*), an AIGateway, or a bare AIProvider.
    """

    def __init__(self, target: Any = None, *, max_tokens: int = DEFAULT_MAX_TOKENS,
                 assessment_id: str = "default") -> None:
        self.max_tokens = max_tokens
        self.assessment_id = assessment_id
        self._target = target
        if target is None:
            from driftguard_platform.ai_runtime import readiness
            ready = readiness()
            if not ready["ready"]:
                need = ", ".join(ready["missing"]) or ready["reason"]
                raise ClaudeProviderError(f"AI provider not ready ({need}): set DRIFTGUARD_AI_PROVIDER, DRIFTGUARD_AI_MODEL and the provider key")
            self.model, self.provider = ready["model"], ready["provider"]
        else:
            self.model, self.provider = getattr(target, "model", "") or "", getattr(target, "name", "") or ""

    # -- prompt construction -------------------------------------------------
    @staticmethod
    def build_payload(request: SemanticEvaluationRequest) -> dict:
        """The exact object sent to the provider: the request, and only it (grounded fields only)."""
        return request.to_dict()

    def build_ai_request(self, request: SemanticEvaluationRequest):
        from driftguard_platform.ai import AIOperation, AIRequest
        return AIRequest(
            AIOperation.SEMANTIC_EVALUATE,
            json.dumps(self.build_payload(request), sort_keys=True, ensure_ascii=False),
            {}, (request.condition_id,),
            schema=RESPONSE_SCHEMA, system=SYSTEM_PROMPT, max_output_tokens=self.max_tokens,
        )

    # -- the contract method -------------------------------------------------
    def evaluate(self, request: SemanticEvaluationRequest) -> SemanticEvaluationResult:
        """Run one semantic evaluation. Output is untrusted until validate_semantic_result accepts it."""
        if not isinstance(request, SemanticEvaluationRequest):
            raise ClaudeProviderError(
                f"request must be a SemanticEvaluationRequest, got {type(request).__name__}"
            )
        from driftguard_platform.ai_runtime import run_with
        outcome = run_with(self._target, self.build_ai_request(request), self.assessment_id)
        if not outcome.ok:
            cls = ClaudeOutputError if outcome.reason_code == "UNUSABLE_OUTPUT" else ClaudeProviderError
            raise cls(f"AI request failed ({outcome.reason_code}): {outcome.detail}")
        return self._to_result(dict(outcome.result.data), request)

    # -- response handling ---------------------------------------------------
    @staticmethod
    def _to_result(
        payload: dict, request: SemanticEvaluationRequest
    ) -> SemanticEvaluationResult:
        """Map provider output onto the result dataclass. No value is repaired."""
        allowed = set(_REQUIRED_FIELDS) | set(_OPTIONAL_FIELDS)
        unexpected = sorted(set(payload) - allowed)
        if unexpected:
            raise ClaudeOutputError(f"Claude output carries unexpected field(s): {unexpected}")
        missing = [f for f in _REQUIRED_FIELDS if f not in payload]
        if missing:
            raise ClaudeOutputError(f"Claude output is missing required field(s): {missing}")

        assessment = payload["assessment"]
        if not isinstance(assessment, str):
            raise ClaudeOutputError(
                f"'assessment' must be a string, got {type(assessment).__name__}"
            )

        confidence = payload["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ClaudeOutputError(
                f"'confidence' must be a number, got {type(confidence).__name__}"
            )

        needs_review = payload["needs_human_review"]
        if not isinstance(needs_review, bool):
            raise ClaudeOutputError(
                f"'needs_human_review' must be a boolean, got {type(needs_review).__name__}"
            )

        present = _string_tuple(payload["present_elements"], "present_elements")
        missing_elements = _string_tuple(payload["missing_elements"], "missing_elements")
        reason_codes = _string_tuple(payload["reason_codes"], "reason_codes")

        finding = payload.get("indicates_finding")
        if finding is not None and not isinstance(finding, str):
            raise ClaudeOutputError(
                f"'indicates_finding' must be a string or null, got {type(finding).__name__}"
            )

        notes = _string_tuple(payload["notes"], "notes") if "notes" in payload else ()

        # Identity is taken from the grounded request, not from the model: the
        # provider is never given the chance to choose which condition or
        # question it answered. Everything the model did assert - verdict,
        # confidence, elements, reason codes, finding - is passed through
        # unchanged for validate_semantic_result() to accept or reject.
        return SemanticEvaluationResult(
            result_id=(
                f"SEMRES-CLAUDE-{request.condition_id}-{uuid.uuid4().hex[:12].upper()}"
            ),
            condition_id=request.condition_id,
            question_id=request.question_id,
            assessment=assessment,
            confidence=confidence,
            present_elements=present,
            missing_elements=missing_elements,
            reason_codes=reason_codes,
            needs_human_review=needs_review,
            indicates_finding=finding,
            notes=notes,
        )


class ClaudeSemanticEvaluator(GatewaySemanticEvaluator):
    """Backward-compatible Claude entry point, now a thin wrapper over the gateway path.

    With client/model given it runs one bare AnthropicProvider through run_with (the SDK client is
    injectable, as before). Model id: model=, else DRIFTGUARD_AI_MODEL, else the deprecated
    DRIFTGUARD_CLAUDE_MODEL.
    """

    def __init__(self, client: Any = None, *, api_key: Optional[str] = None, model: Optional[str] = None,
                 max_tokens: int = DEFAULT_MAX_TOKENS, timeout: Optional[float] = None) -> None:
        resolved = model or os.environ.get("DRIFTGUARD_AI_MODEL") or os.environ.get(ENV_MODEL)
        if not resolved:
            raise ClaudeProviderError(
                f"no Claude model configured: set DRIFTGUARD_AI_MODEL (deprecated: {ENV_MODEL}) to a model id "
                f"your Anthropic account/SDK supports, or pass model= explicitly"
            )
        from driftguard_platform.ai import AnthropicProvider
        provider = AnthropicProvider(
            api_key=api_key, model=resolved, max_output_tokens=max_tokens,
            client=client if client is not None else self._build_client(api_key, timeout),
        )
        super().__init__(provider, max_tokens=max_tokens)
        self.model, self.provider = resolved, "anthropic"

    @staticmethod
    def _build_client(api_key: Optional[str], timeout: Optional[float]) -> Any:
        """Construct a real Anthropic client. Credentials are never hard-coded, logged or echoed."""
        try:
            import anthropic  # imported lazily: optional dependency
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ClaudeProviderError(
                "the anthropic SDK is not installed; `pip install anthropic` "
                "or inject a client explicitly"
            ) from exc
        kwargs: dict = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if timeout is not None:
            kwargs["timeout"] = timeout
        return anthropic.Anthropic(**kwargs)


# ------------------------------------------------------------------- helpers
def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ClaudeOutputError(f"{field!r} must be an array of strings")
    return tuple(value)
