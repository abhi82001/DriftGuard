from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import hashlib,hmac,json,time,uuid
@dataclass(frozen=True)
class ServiceCredential: credential_id:str; tenant_id:str; scopes:frozenset[str]; revoked:bool=False

def authorize(cred:ServiceCredential,tenant_id:str,scope:str):
    if cred.revoked: raise PermissionError("credential revoked")
    if cred.tenant_id!=tenant_id: raise PermissionError("cross-tenant access denied")
    if scope not in cred.scopes: raise PermissionError("scope denied")

def idempotency_key(tenant_id:str,payload:Any)->str:
    return hashlib.sha256((tenant_id+json.dumps(payload,sort_keys=True,default=str)).encode()).hexdigest()

def sign_webhook(secret:str,timestamp:int,payload:bytes)->str:
    return hmac.new(secret.encode(),str(timestamp).encode()+b"."+payload,hashlib.sha256).hexdigest()
def verify_webhook(secret:str,timestamp:int,payload:bytes,signature:str,max_age=300,now=None)->bool:
    now=int(now or time.time())
    if abs(now-timestamp)>max_age:return False
    return hmac.compare_digest(sign_webhook(secret,timestamp,payload),signature)
