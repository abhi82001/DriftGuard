from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Mapping, Any
from .ai import AIRequest, AIOperation
from .ai_runtime import run_with
INSUFFICIENT = "I don't have sufficient evidence to answer that."
@dataclass(frozen=True)
class AssistantContext: tenant_id:str; sources:tuple[str,...]; facts:tuple[Mapping[str,Any],...]; assessment:Mapping[str,Any]

# `provider` may be an AIProvider or an AIGateway.
def grounded_answer(provider, question:str, context:AssistantContext)->str:
    if not context.sources: return INSUFFICIENT
    payload={"question":question,"facts":context.facts,"assessment":context.assessment,"rule":"Explain only; do not alter assessment."}
    out=run_with(provider,AIRequest(AIOperation.EXPLAIN,str(payload),{"tenant_id":context.tenant_id},context.sources))
    if not out.ok: return INSUFFICIENT
    return str(out.result.data.get("answer",INSUFFICIENT))
