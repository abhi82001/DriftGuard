"""Adapter from canonical CP010 NarrativeFact objects to CP009 SecurityClaims."""
from __future__ import annotations
from typing import Iterable
from dataclasses import replace
from ingestion import Document
from claims import SecurityClaim
from narrative_intelligence import extract_narrative_facts

DESIGN={"POLICY","PROCEDURE"}
OPERATING={"CONFIGURATION","REPORT","TICKET","REGISTER","TEST_RESULT","OPERATING_EVIDENCE"}

def _cp009_role(role: str) -> str:
    if role in DESIGN: return role
    if role == "CONFIGURATION": return "CONFIGURATION"
    if role in OPERATING: return "OPERATING_EVIDENCE"
    return "UNKNOWN"

class GroundedNarrativeClaimExtractor:
    source="deterministic-grounded-v1"
    def extract(self, documents: Iterable[Document]) -> list[SecurityClaim]:
        out=[]
        for fact in extract_narrative_facts(documents):
            # Preserve negative/planned/conditional facts for diagnostics but do
            # not turn them into affirmative CP009 contract attributes.
            if any(q in fact.qualifiers for q in ("NEGATED","PLANNED_OR_FUTURE","CONDITIONAL")):
                continue
            out.append(SecurityClaim(
                topic=fact.concept,
                statement=fact.provenance.excerpt[:220],
                source_filename=fact.provenance.filename,
                source_locator=fact.provenance.locator,
                snippet=fact.provenance.excerpt,
                evidence_nature=_cp009_role(fact.source_role),
                attributes={fact.attribute: fact.normalized_value},
                extraction_method=fact.extraction_method,
                artifact_type=fact.artifact_type,
                evidence_date=fact.effective_date,
            ))
        return out

class CompositeGroundedExtractor:
    """Preserve proven legacy rules while adding canonical CP010 facts."""
    source="deterministic-grounded-v1+legacy"
    def __init__(self):
        from claims import DemoClaimExtractor
        self.legacy=DemoClaimExtractor()
        self.grounded=GroundedNarrativeClaimExtractor()
    def extract(self, documents):
        docs=list(documents)
        combined=self.legacy.extract(docs)+self.grounded.extract(docs)
        out=[]; seen=set()
        for c in combined:
            key=(c.topic,c.source_filename,c.source_locator,tuple(sorted((k,repr(v)) for k,v in c.attributes.items())))
            if key not in seen:
                seen.add(key); out.append(c)
        return out

class SemanticGroundedClaimExtractor:
    """CP012 adapter: validated semantic facts -> existing CP009 SecurityClaims."""
    source="semantic-grounded-v1"
    def __init__(self, provider): self.provider=provider; self.rejections=[]
    def extract(self, documents):
        from narrative_intelligence import classify_source_role
        from semantic_extraction import extract_document, SemanticRejection
        from semantic_runtime import SemanticRuntimeConfig
        from ingestion import Document
        cfg=SemanticRuntimeConfig.from_env(); remaining=cfg.max_segments
        out=[]; self.rejections=[]
        for document in documents:
            if remaining <= 0:
                self.rejections.append(SemanticRejection(document.filename,"document","semantic segment budget exhausted")); continue
            eligible=[]
            for chunk in document.chunks:
                if remaining <= 0: break
                if len(chunk.text) > cfg.max_segment_chars:
                    self.rejections.append(SemanticRejection(document.filename,chunk.locator,"segment exceeds semantic character budget")); continue
                eligible.append(chunk); remaining-=1
            if not eligible: continue
            scoped=Document(document.filename,document.kind,tuple(eligible))
            role=classify_source_role(document)
            facts,rejected=extract_document(scoped,self.provider,role)
            self.rejections.extend(rejected)
            for fact in facts:
                # Materially qualified semantic statements stay diagnostic facts;
                # they are not promoted into affirmative questionnaire evidence.
                if any(q in fact.qualifiers for q in ("NEGATED","PLANNED_OR_FUTURE","CONDITIONAL")):
                    continue
                out.append(SecurityClaim(topic=fact.concept,statement=fact.provenance.excerpt[:220],source_filename=fact.provenance.filename,source_locator=fact.provenance.locator,snippet=fact.provenance.excerpt,evidence_nature=_cp009_role(fact.source_role),attributes={fact.attribute:fact.normalized_value},extraction_method=fact.extraction_method,artifact_type=fact.artifact_type,evidence_date=fact.effective_date))
        return out

class HybridGroundedExtractor:
    """Deterministic CP010 extraction plus explicitly configured CP012 provider."""
    source="hybrid-grounded-v1"
    def __init__(self,provider=None):
        self.deterministic=CompositeGroundedExtractor(); self.semantic=SemanticGroundedClaimExtractor(provider) if provider else None
        self.semantic_status="SEMANTIC_ACTIVE" if provider else "NEEDS_REVIEW"
        self.semantic_rejections=[]; self.semantic_conflicts=[]
    def extract(self,documents):
        docs=list(documents); deterministic=self.deterministic.extract(docs); combined=list(deterministic)
        self.semantic_rejections=[]; self.semantic_conflicts=[]
        if self.semantic:
            semantic_claims=self.semantic.extract(docs); self.semantic_rejections=list(self.semantic.rejections)
            # Deterministic facts have priority for the same grounded source location
            # and canonical attribute. A disagreeing model claim is surfaced, never
            # silently allowed to override the deterministic fact.
            det_index={}
            for c in deterministic:
                for attr,val in c.attributes.items(): det_index[(c.topic,c.source_filename,c.source_locator,attr)]=val
            for c in semantic_claims:
                keep={}
                for attr,val in c.attributes.items():
                    k=(c.topic,c.source_filename,c.source_locator,attr)
                    if k in det_index:
                        if repr(det_index[k]) != repr(val):
                            self.semantic_conflicts.append({"topic":c.topic,"attribute":attr,"source_file":c.source_filename,"source_locator":c.source_locator,"deterministic_value":det_index[k],"semantic_value":val})
                        continue
                    keep[attr]=val
                if keep:
                    combined.append(replace(c, attributes=keep))
            if self.semantic_rejections and not any(c.extraction_method=="semantic-grounded-v1" for c in combined):
                if all(r.reason.startswith("provider error:") for r in self.semantic_rejections): self.semantic_status="SEMANTIC_FAILED"
        out=[]; seen=set()
        for c in combined:
            key=(c.topic,c.source_filename,c.source_locator,tuple(sorted((k,repr(v)) for k,v in c.attributes.items())))
            if key not in seen: seen.add(key); out.append(c)
        return out
