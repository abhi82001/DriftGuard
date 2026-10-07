from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class Framework: key:str; version:str; controls:frozenset[str]
class FrameworkRegistry:
    def __init__(self): self._items={}
    def register(self,f:Framework): self._items[(f.key,f.version)]=f
    def get(self,key,version): return self._items[(key,version)]
    def list(self): return tuple(self._items.values())
registry=FrameworkRegistry()
registry.register(Framework("SOC2","2017",frozenset({"CC6","CC7"})))
registry.register(Framework("ISO27001","2022",frozenset()))
registry.register(Framework("DPDP","2023",frozenset()))
@dataclass(frozen=True)
class FrameworkMapping: source_framework:str; source_control:str; target_framework:str; target_control:str; authoritative:bool=True
