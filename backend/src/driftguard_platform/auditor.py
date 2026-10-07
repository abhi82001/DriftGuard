from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class AuditTrace:
    framework:str; control:str; requirement:str; evidence_ids:tuple[str,...]; fact_ids:tuple[str,...]; evaluation:str; finding_ids:tuple[str,...]=(); remediation_ids:tuple[str,...]=(); ai_derived:bool=False
    def validate(self):
        if not self.framework or not self.control or not self.requirement: raise ValueError("audit trace missing control lineage")
        if not self.evidence_ids: raise ValueError("audit trace must link evidence")
        return self
