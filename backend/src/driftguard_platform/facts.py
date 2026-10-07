from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable
import hashlib, json

@dataclass(frozen=True)
class FactSource:
    artifact_id: str; locator: str; excerpt: str=""
@dataclass(frozen=True)
class CanonicalFact:
    subject: str; predicate: str; value: Any; source: FactSource
    unit: str=""; scope: str=""; effective_date: str=""; period: str=""; confidence: float=1.0
    extraction_method: str="deterministic"; qualifiers: tuple[tuple[str,str],...]=()
    @property
    def fact_id(self):
        raw=json.dumps([self.subject,self.predicate,self.value,self.source.artifact_id,self.source.locator],default=str,sort_keys=True)
        return "FACT-"+hashlib.sha256(raw.encode()).hexdigest()[:16]

def validate_fact(f:CanonicalFact)->CanonicalFact:
    if not f.subject or not f.predicate or not f.source.artifact_id or not f.source.locator: raise ValueError("canonical facts require subject, predicate and provenance")
    if not 0 <= f.confidence <= 1: raise ValueError("confidence must be in [0,1]")
    return f

def deduplicate_facts(facts:Iterable[CanonicalFact])->tuple[CanonicalFact,...]:
    out={}
    for f in facts:
        validate_fact(f); key=(f.subject,f.predicate,json.dumps(f.value,default=str,sort_keys=True),f.source.artifact_id,f.source.locator)
        old=out.get(key); out[key]=f if old is None or f.confidence>old.confidence else old
    return tuple(out.values())
