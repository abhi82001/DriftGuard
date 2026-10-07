from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable
import time
@dataclass(frozen=True)
class ConnectorRecord: external_id:str; kind:str; data:Mapping[str,Any]; source:str
@dataclass(frozen=True)
class SyncResult: connector:str; records:tuple[ConnectorRecord,...]; cursor:str|None=None; warnings:tuple[str,...]=()
@runtime_checkable
class Connector(Protocol):
    name:str
    def test_connection(self)->bool: ...
    def collect(self,cursor:str|None=None)->SyncResult: ...
class ConnectorRegistry:
    def __init__(self): self._factories={}
    def register(self,name,factory): self._factories[name]=factory
    def create(self,name,**kw):
        if name not in self._factories: raise KeyError(f"unsupported connector: {name}")
        return self._factories[name](**kw)
registry=ConnectorRegistry()

class OktaConnector:
    """Reference IAM connector. HTTP client is injectable for deterministic tests."""
    name='okta'
    def __init__(self, base_url:str, token:str, client=None):
        if not base_url.startswith('https://'): raise ValueError('Okta base_url must use https')
        if not token: raise ValueError('Okta token is required')
        self.base_url=base_url.rstrip('/'); self._token=token; self._client=client
    def _http(self):
        if self._client is not None:return self._client
        import httpx
        return httpx.Client(timeout=20,headers={'Authorization':f'SSWS {self._token}','Accept':'application/json'})
    def test_connection(self)->bool:
        r=self._http().get(self.base_url+'/api/v1/users',params={'limit':1}); return r.status_code==200
    def collect(self,cursor:str|None=None)->SyncResult:
        url=cursor or self.base_url+'/api/v1/users'; r=self._http().get(url,params=None if cursor else {'limit':200}); r.raise_for_status()
        records=[]
        for u in r.json():
            profile=u.get('profile') or {}
            records.append(ConnectorRecord(str(u.get('id','')),'IDENTITY_PROVIDER_EXPORT',{
                'user_id':u.get('id',''),'status':u.get('status',''),'email':profile.get('email',''),
                'login':profile.get('login',''),'last_updated':u.get('lastUpdated','')},'okta'))
        next_cursor=None
        link=r.headers.get('link','')
        for part in link.split(','):
            if 'rel="next"' in part and '<' in part and '>' in part: next_cursor=part.split('<',1)[1].split('>',1)[0]
        return SyncResult(self.name,tuple(records),next_cursor)

registry.register('okta',lambda **kw:OktaConnector(**kw))

@dataclass(frozen=True)
class ConnectorConfig:
    """Serializable connector settings. Secret values are references, never credentials."""
    provider: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    secret_refs: Mapping[str, str] = field(default_factory=dict)


def connector_for(config: ConnectorConfig, *, secret_provider, connector_registry: ConnectorRegistry = registry) -> Connector:
    kwargs = dict(config.settings)
    for argument, reference in config.secret_refs.items():
        kwargs[argument] = secret_provider.get(reference)
    return connector_registry.create(config.provider, **kwargs)
