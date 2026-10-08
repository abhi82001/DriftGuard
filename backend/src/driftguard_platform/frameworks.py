from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
@dataclass(frozen=True)
class Framework: key:str; version:str; controls:frozenset[str]
class FrameworkRegistry:
    def __init__(self): self._items={}
    def register(self,f:Framework): self._items[(f.key,f.version)]=f
    def get(self,key,version): return self._items[(key,version)]
    def list(self): return tuple(self._items.values())
    def load_directory(self,root):
        """Register the framework held in a knowledge directory (knowledge/<framework>/)."""
        f=load_framework(root)
        if f: self.register(f)
        return f
def _group(control):
    """Control group: explicit ``control_group``, else the criterion series (CC6.1 -> CC6)."""
    if control.get("control_group"): return control["control_group"]
    m=re.match(r"[A-Za-z]+\d+",control.get("criterion",""))
    return m.group(0) if m else control.get("criterion","")
def load_framework(root):
    """Build a Framework from ``framework/metadata.json`` and ``controls/`` (None if absent)."""
    import json
    root=Path(root); meta=root/"framework"/"metadata.json"
    if not meta.is_file(): return None
    m=json.loads(meta.read_text(encoding="utf-8"))
    groups={_group(json.loads(p.read_text(encoding="utf-8"))) for p in (root/"controls").glob("*.json")}
    return Framework(m["framework"],str(m.get("registry_version","")),frozenset(g for g in groups if g))
registry=FrameworkRegistry()
_KNOWLEDGE=Path(__file__).resolve().parents[3]/"knowledge"
if not (_KNOWLEDGE/"soc2").is_dir(): registry.register(Framework("SOC2","2017",frozenset({"CC6","CC7"})))
for _d in sorted(_KNOWLEDGE.glob("*/")) if _KNOWLEDGE.is_dir() else (): registry.load_directory(_d)
# Frameworks with no knowledge yet stay registered, empty, until knowledge/<framework>/ exists.
for _f in (Framework("ISO27001","2022",frozenset()),Framework("DPDP","2023",frozenset())):
    if not any(i.key==_f.key for i in registry.list()): registry.register(_f)
@dataclass(frozen=True)
class FrameworkMapping: source_framework:str; source_control:str; target_framework:str; target_control:str; authoritative:bool=True
