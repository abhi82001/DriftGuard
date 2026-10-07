from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from .facts import FactSource

STATES=("DESIGN_EVIDENCED","OPERATING_EVIDENCED","PARTIALLY_EVIDENCED","EXCEPTION_IDENTIFIED","CONFLICT","INSUFFICIENT_EVIDENCE")
@dataclass(frozen=True)
class PolicyRequirement:
    requirement_id:str; subject:str; predicate:str; operator:str; expected:Any; source:FactSource; unit:str=""; effective_from:str=""; effective_to:str=""
@dataclass(frozen=True)
class EffectivenessResult:
    requirement_id:str; state:str; observed:Any; detail:str; sources:tuple[FactSource,...]

def evaluate_requirement(req:PolicyRequirement, observed:Any, operating_source:FactSource|None)->EffectivenessResult:
    if observed is None or operating_source is None: return EffectivenessResult(req.requirement_id,"INSUFFICIENT_EVIDENCE",observed,"No grounded operating evidence was supplied.",(req.source,))
    ops={"eq":lambda a,b:a==b,"lte":lambda a,b:a<=b,"gte":lambda a,b:a>=b,"lt":lambda a,b:a<b,"gt":lambda a,b:a>b}
    if req.operator not in ops: return EffectivenessResult(req.requirement_id,"CONFLICT",observed,"Unsupported or conflicting requirement operator.",(req.source,operating_source))
    try: ok=ops[req.operator](observed,req.expected)
    except (TypeError,ValueError): return EffectivenessResult(req.requirement_id,"CONFLICT",observed,"Requirement and operating value cannot be compared deterministically.",(req.source,operating_source))
    return EffectivenessResult(req.requirement_id,"OPERATING_EVIDENCED" if ok else "EXCEPTION_IDENTIFIED",observed,"Operating evidence satisfies the documented requirement." if ok else "Operating evidence does not satisfy the documented requirement.",(req.source,operating_source))
