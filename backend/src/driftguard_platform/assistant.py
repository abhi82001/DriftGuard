from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Mapping, Any
from .ai import AIProvider, AIRequest, AIOperation, validate_result
@dataclass(frozen=True)
class AssistantContext: tenant_id:str; sources:tuple[str,...]; facts:tuple[Mapping[str,Any],...]; assessment:Mapping[str,Any]

def grounded_answer(provider:AIProvider, question:str, context:AssistantContext)->str:
    if not context.sources: return "I don't have sufficient evidence to answer that."
    payload={"question":question,"facts":context.facts,"assessment":context.assessment,"rule":"Explain only; do not alter assessment."}
    r=validate_result(provider.execute(AIRequest(AIOperation.EXPLAIN,str(payload),{"tenant_id":context.tenant_id},context.sources)))
    return str(r.data.get("answer","I don't have sufficient evidence to answer that."))
