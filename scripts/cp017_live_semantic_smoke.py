#!/usr/bin/env python3
"""Opt-in CP017 real-provider smoke test. Never prints API keys or raw credentials."""
from pathlib import Path
import json, os, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'/'src'))
from ingestion import Document,Chunk
from semantic_extraction import configured_provider,build_request,extract_document
from narrative_intelligence import classify_source_role

def main():
    provider,status=configured_provider()
    if not provider:
        print(json.dumps({'result':'NOT_RUN','semantic_status':status,'reason':'Real Claude provider is not fully configured (provider/model/API key/SDK required).'}))
        return 2
    text='Production administrators authenticate through the central identity service using an additional verification factor.'
    d=Document('cp017-live-smoke.txt','artifact',(Chunk('cp017-live-smoke.txt','line 1',text,heading='Authentication',segment_type='line'),))
    role=classify_source_role(d)
    facts,rejections=extract_document(d,provider,role)
    safe={'result':'PASS' if facts else 'NO_GROUNDED_FACT','semantic_status':status,'accepted_facts':len(facts),'rejections':[r.reason for r in rejections]}
    print(json.dumps(safe,indent=2))
    return 0 if facts else 1
if __name__=='__main__': raise SystemExit(main())
