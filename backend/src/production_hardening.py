"""Production boundary helpers: privacy-safe telemetry and bounded lifecycle state."""
from __future__ import annotations
import logging, time
from collections import OrderedDict
from dataclasses import dataclass

log = logging.getLogger("driftguard.ops")

SENSITIVE_KEYS={"excerpt","supporting_quote","text","content","document","payload"}

def safe_event(event:str, **fields)->None:
    clean={k:v for k,v in fields.items() if k not in SENSITIVE_KEYS}
    log.info("driftguard_event=%s %s", event, " ".join(f"{k}={v}" for k,v in sorted(clean.items())))

def neutralize_formula(value:object)->str:
    s="" if value is None else str(value)
    # Spreadsheet formula injection: preserve evidence literally but make it inert if exported/opened.
    return "'"+s if s.lstrip().startswith(("=","+","-","@")) else s

@dataclass
class _Entry:
    value: object
    created: float

class BoundedAssessmentStore:
    def __init__(self,max_items:int=500,ttl_seconds:int=8*3600):
        self.max_items=max_items; self.ttl_seconds=ttl_seconds; self._data=OrderedDict()
    def _purge(self):
        now=time.monotonic()
        for k in list(self._data):
            if now-self._data[k].created>self.ttl_seconds: self._data.pop(k,None)
        while len(self._data)>self.max_items: self._data.popitem(last=False)
    def __setitem__(self,key,value):
        self._purge(); self._data[key]=_Entry(value,time.monotonic()); self._data.move_to_end(key); self._purge()
    def __getitem__(self,key):
        value=self.get(key, None)
        if value is None: raise KeyError(key)
        return value
    def get(self,key,default=None):
        self._purge(); e=self._data.get(key)
        if not e:return default
        self._data.move_to_end(key); return e.value
    def pop(self,key,default=None):
        e=self._data.pop(key,None); return default if e is None else e.value
    def __contains__(self,key): return self.get(key) is not None
    def __len__(self): self._purge(); return len(self._data)
