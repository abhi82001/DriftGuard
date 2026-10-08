from __future__ import annotations
from dataclasses import dataclass
from .ai import AIRequest, AIOperation
from .ai_runtime import run_with
from .facts import CanonicalFact, FactSource, validate_fact

@dataclass(frozen=True)
class Classification: artifact_type:str; confidence:float; source_ids:tuple[str,...]; alternatives:tuple[str,...]=()

# `provider` may be an AIProvider or an AIGateway; if AI is unavailable the result degrades safely.
def classify_unknown(provider, *, content:str, source_id:str, deterministic_type:str="UNCLASSIFIED", deterministic_confidence:float=0.0, threshold:float=.80)->Classification:
    if deterministic_type!="UNCLASSIFIED" and deterministic_confidence>=threshold:
        return Classification(deterministic_type,deterministic_confidence,(source_id,))
    out=run_with(provider,AIRequest(AIOperation.CLASSIFY,content,{"deterministic_type":deterministic_type,"deterministic_confidence":deterministic_confidence},(source_id,)))
    if not out.ok: return Classification("UNCLASSIFIED",0.0,(source_id,))
    r=out.result
    return Classification(str(r.data.get("artifact_type","UNCLASSIFIED")),r.confidence,r.source_ids,tuple(r.data.get("alternatives",())))

def extract_candidate_facts(provider, *, content:str, source_id:str)->tuple[CanonicalFact,...]:
    out=run_with(provider,AIRequest(AIOperation.EXTRACT,content,{},(source_id,)))
    if not out.ok: return ()
    r=out.result
    facts=[]
    for x in r.data.get("facts",[]):
        locator=str(x.get("locator","")).strip()
        if not locator: continue
        f=CanonicalFact(str(x.get("subject","")).strip(),str(x.get("predicate","")).strip(),x.get("value"),FactSource(source_id,locator,str(x.get("excerpt",""))),str(x.get("unit","")),str(x.get("scope","")),str(x.get("effective_date","")),str(x.get("period","")),float(x.get("confidence",r.confidence)),"ai")
        try: facts.append(validate_fact(f))
        except ValueError: continue
    return tuple(facts)
