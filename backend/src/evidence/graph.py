"""CP013 provenance-aware cross-artifact evidence graph.

Only exact or explicitly-normalized identifiers are joined. No fuzzy matching is
performed. Graph observations request review; they are never compliance verdicts.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterable
from .tabular import normalize

@dataclass(frozen=True)
class GraphProvenance:
    filename: str
    sheet: str
    locator: str
    excerpt: str = ""

@dataclass(frozen=True)
class GraphNode:
    node_id: str
    entity_type: str
    key: str
    label: str
    attributes: tuple[tuple[str,str], ...] = ()
    provenance: tuple[GraphProvenance, ...] = ()

@dataclass(frozen=True)
class GraphEdge:
    edge_type: str
    source: str
    target: str
    provenance: tuple[GraphProvenance, ...]
    explanation: str

@dataclass(frozen=True)
class GraphObservation:
    code: str
    state: str
    relationship: str
    detail: str
    identifiers: tuple[str, ...]
    provenance: tuple[GraphProvenance, ...]

@dataclass
class EvidenceGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    observations: list[GraphObservation] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    coverage: dict[str, dict] = field(default_factory=dict)

# relationship, left kind, right kind, aliases shared by both, edge
RELATIONSHIPS = (
 ('HR roster ↔ IdP identities','HR_ACTIVE_WORKER_ROSTER','IDENTITY_PROVIDER_EXPORT',(('employee id','user id','employee','email'),),'BELONGS_TO'),
 ('IdP ↔ access review','IDENTITY_PROVIDER_EXPORT','USER_ACCESS_REVIEW',(('user id','user','account','email'),),'REVIEWED_BY'),
 ('access review ↔ remediation','USER_ACCESS_REVIEW','PRODUCTION_CHANGE_TICKETS',(('ticket','ticket id','change','remediation ticket'),),'REMEDIATED_BY'),
 ('termination ↔ account disablement','TERMINATION_REPORT','IDENTITY_PROVIDER_EXPORT',(('employee','user id','employee id','email'),),'CONFIRMS'),
 ('asset inventory ↔ endpoint protection','ASSET_INVENTORY','ENDPOINT_PROTECTION_COVERAGE',(('asset id','asset','hostname','device'),),'COVERS'),
 ('asset inventory ↔ disk encryption','ASSET_INVENTORY','DISK_ENCRYPTION_REPORT',(('asset id','asset','hostname','device'),),'COVERS'),
 ('asset inventory ↔ vulnerability scan','ASSET_INVENTORY','VULNERABILITY_REMEDIATION',(('asset id','asset','hostname','device','system'),),'COVERS'),
 ('data inventory ↔ deletion records','DATA_INVENTORY','DATA_DELETION_RECORD',(('dataset',),),'CONFIRMS'),
 ('firewall baseline ↔ firewall export','FIREWALL_BASELINE','FIREWALL_RULE_EXPORT',(('rule id','rule'),),'IMPLEMENTS'),
 ('vulnerability ↔ remediation ticket','VULNERABILITY_REMEDIATION','PRODUCTION_CHANGE_TICKETS',(('ticket','ticket id','change','remediation ticket'),),'REMEDIATED_BY'),
 ('incident ↔ postmortem','INCIDENT_RECORD','INCIDENT_POSTMORTEM',(('incident','incident id'),),'CONFIRMS'),
 ('DR plan ↔ DR test','DR_PLAN','DR_TEST',(('system','service','application'),),'CONFIRMS'),
 ('backup system ↔ backup execution','ASSET_INVENTORY','BACKUP_JOB_REPORT',(('hostname','system','asset'),),'COVERS'),
 ('risk ↔ treatment/remediation','RISK_REGISTER','PRODUCTION_CHANGE_TICKETS',(('ticket','ticket id','change','remediation ticket'),),'REMEDIATED_BY'),
)

def norm_identifier(value: str, kind: str='generic') -> str:
    v=normalize(value)
    if kind in {'hostname','system','asset','device'}:
        return v.split('.')[0]
    if kind in {'email','employee','employee id','user id','user','account'}:
        return v.split('@',1)[0]
    return v

def _category(alias):
    return ('asset_id' if alias == 'asset id' else 'ambiguous_asset' if alias == 'asset' else 'host' if alias in {'hostname','device','system'} else 'person' if alias in {'employee id','user id','employee','email','user','account'} else 'ticket' if alias in {'ticket','ticket id','change','remediation ticket'} else alias)

def _records_for(workbook, sheet, alias):
    c=sheet.column_of(alias)
    if c is None: return None
    out={}
    for row in sheet.data_rows:
        cell=row.cell(c); raw=cell.text if cell else ''
        key=norm_identifier(raw, alias)
        if key:
            p=GraphProvenance(workbook.filename,sheet.name,cell.ref,raw)
            out.setdefault(key,[]).append((row,p))
    return _category(alias),out

def _best_pair(lb,ls,rb,rs,aliases):
    candidates=[]
    for la in aliases:
      L=_records_for(lb,ls,la)
      if L is None: continue
      for ra in aliases:
        R=_records_for(rb,rs,ra)
        if R is None: continue
        compatible = L[0] == R[0] or 'ambiguous_asset' in {L[0],R[0]}
        if not compatible: continue
        overlap=len(set(L[1]) & set(R[1]))
        candidates.append((overlap,la,ra,L[1],R[1]))
    if not candidates: return None
    candidates.sort(key=lambda x:(x[0], x[1]==x[2]), reverse=True)
    best=candidates[0]
    # If no identifiers overlap, only use same-named columns; otherwise do not infer namespace semantics.
    if best[0]==0:
        same=[x for x in candidates if x[1]==x[2]]
        if not same: return None
        best=same[0]
    return best[3],best[4],best[1],best[2]

def _row_value(sheet, row, *names):
    c=sheet.column_of(*names)
    cell=row.cell(c) if c else None
    return normalize(cell.text) if cell else ''

def _relationship_conflicts(g, rel, left, right, key, L, R, ls, rs):
    for ident in sorted(set(L)&set(R)):
        for lr,lp in L[ident]:
          for rr,rp in R[ident]:
            if rel == 'HR roster ↔ IdP identities':
                hr=_row_value(ls,lr,'employment status','status'); status=_row_value(rs,rr,'status')
                if hr in {'terminated','inactive','separated','left','leaver'} and status in {'active','enabled'}:
                    g.observations.append(GraphObservation('CROSS-ARTIFACT-CONFLICT','CONFLICT',rel,
                        f'{ident!r}: HR evidence records the worker terminated while IdP evidence records the identity active.',(ident,),(lp,rp)))
            elif rel == 'asset inventory ↔ endpoint protection':
                expected=_row_value(ls,lr,'edr'); actual=_row_value(rs,rr,'edr installed')
                if expected in {'yes','true','required','expected'} and actual in {'no','false','missing','not installed'}:
                    g.observations.append(GraphObservation('CROSS-ARTIFACT-CONFLICT','CONFLICT',rel,
                        f'{ident!r}: asset inventory expects EDR but endpoint evidence records it as not installed.',(ident,),(lp,rp)))
                    g.observations.append(GraphObservation('EDR-COVERAGE-GAP','NEEDS_REVIEW',rel,
                        f'{ident!r}: endpoint coverage is absent/not installed; this is a coverage observation requiring review, not a control failure.',(ident,),(lp,rp)))
            elif rel == 'termination ↔ account disablement':
                term=_row_value(ls,lr,'current iam status'); status=_row_value(rs,rr,'status')
                if term in {'disabled','terminated','revoked','inactive'} and status in {'active','enabled'}:
                    g.observations.append(GraphObservation('CROSS-ARTIFACT-CONFLICT','CONFLICT',rel,
                        f'{ident!r}: termination evidence records access disabled/revoked while IdP evidence records the identity active.',(ident,),(lp,rp)))
            elif rel in {'vulnerability ↔ remediation ticket','risk ↔ treatment/remediation'}:
                left_status=_row_value(ls,lr,'status'); ticket_status=_row_value(rs,rr,'status')
                if ticket_status in {'closed','completed','resolved'} and left_status in {'open','active','unresolved'}:
                    g.observations.append(GraphObservation('CLOSURE-CONFLICT','CONFLICT',rel,
                        f'{ident!r}: remediation ticket is closed but underlying register remains open.',(ident,),(lp,rp)))

def build_evidence_graph(artifacts: Iterable[tuple[str,object,object]]) -> EvidenceGraph:
    g=EvidenceGraph(); indexed={}
    for kind,book,sheet in artifacts:
        indexed.setdefault(kind,[]).append((book,sheet))
        artifact_id=f'artifact:{book.filename}'
        if not any(n.node_id==artifact_id for n in g.nodes):
            g.nodes.append(GraphNode(artifact_id,'EvidenceArtifact',book.filename,book.filename,
                provenance=(GraphProvenance(book.filename,sheet.name,'sheet'),)))
    for rel,left,right,alias_groups,edge_type in RELATIONSHIPS:
        if left not in indexed or right not in indexed: continue
        aliases=alias_groups[0]
        for lb,ls in indexed[left]:
          for rb,rs in indexed[right]:
            pair=_best_pair(lb,ls,rb,rs,aliases)
            if pair is None:
                g.unsupported.append(f'{rel}: no exact compatible identifier column; no inferred/fuzzy join')
                continue
            L,R,left_alias,right_alias=pair
            matched=set(L)&set(R); missing=set(L)-set(R)
            g.coverage[rel]={'source':len(L),'matched':len(matched),'unmatched':len(missing),
                             'percent': round(100*len(matched)/len(L),2) if L else None}
            for key in sorted(matched):
                lps=tuple(p for _,p in L[key]); rps=tuple(p for _,p in R[key]); prov=lps+rps
                lid=f'{left}:{key}'; rid=f'{right}:{key}'
                if not any(n.node_id==lid for n in g.nodes): g.nodes.append(GraphNode(lid,left,key,key,provenance=lps))
                if not any(n.node_id==rid for n in g.nodes): g.nodes.append(GraphNode(rid,right,key,key,provenance=rps))
                g.edges.append(GraphEdge(edge_type,lid,rid,prov,f'{rel}: explicit normalized identifier {key!r} matched.'))
                if len(L[key])>1 or len(R[key])>1:
                    g.observations.append(GraphObservation('AMBIGUOUS-IDENTIFIER','NEEDS_REVIEW',rel,
                        f'Identifier {key!r} occurs multiple times; relationship is one-to-many and was not collapsed.',(key,),prov))
            _relationship_conflicts(g,rel,left,right,'identifier',L,R,ls,rs)
            for key in sorted(missing):
                prov=tuple(p for _,p in L[key])
                g.observations.append(GraphObservation('COVERAGE-GAP','NEEDS_REVIEW',rel,
                    f'{key!r} is present in {left} but has no exact/normalized match in {right}. This is a coverage observation, not a control failure.',(key,),prov))
    return g

def explain(graph: EvidenceGraph, observation: GraphObservation) -> dict:
    return {'code':observation.code,'relationship':observation.relationship,'detail':observation.detail,
            'sources':[{'filename':p.filename,'sheet':p.sheet,'locator':p.locator,'excerpt':p.excerpt} for p in observation.provenance]}

def graph_from_files(files):
    """Build graph inputs from recognized tabular uploads; unreadable/unclassified files are ignored explicitly."""
    from .tabular import is_tabular, read_tabular, TabularError
    from .structured_registry import recognize
    from .classify import classify
    artifacts=[]
    for filename,data in files:
        if not is_tabular(filename): continue
        try: book=read_tabular(filename,data)
        except TabularError: continue
        reg=recognize(book)
        if reg is not None:
            spec,sheet=reg; artifacts.append((spec.kind,book,sheet)); continue
        c=classify(book)
        if c.supported:
            # Specialized evidence type; choose the sheet that carries its detected header.
            sheet=next((s for s in book.sheets if s.headers),book.sheets[0])
            artifacts.append((c.evidence_type,book,sheet))
    return build_evidence_graph(artifacts)
