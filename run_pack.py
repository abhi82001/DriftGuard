#!/usr/bin/env python3
from pathlib import Path
from datetime import date
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).parent/'backend'/'src'))
from app import analyze_payloads
from upload_security import SUPPORTED
from evidence.report import build_question_reports

def prov(p):
 return {'filename':p.filename,'locator':p.locator,'excerpt':getattr(p,'excerpt','')}
def main():
 p=argparse.ArgumentParser();p.add_argument('directory',nargs='?',default=str(Path(__file__).parent/'test_evidence'/'driftguard_soc2_test_pack'));p.add_argument('--output');p.add_argument('--assessment-date');a=p.parse_args(); root=Path(a.directory)
 as_of=date.fromisoformat(a.assessment_date) if a.assessment_date else None
 files=[(x.name,x.read_bytes()) for x in sorted(root.rglob('*')) if x.is_file() and x.suffix.lower() in SUPPORTED]
 r=analyze_payloads(root.name,files,assessment_date=as_of); g=r.evidence_graph
 payload={
  'files_supplied':len(files),'files_processed':len(r.documents),'files_rejected':len(r.errors),'errors':list(r.errors),'extraction':r.extraction,'explainability':build_question_reports(r.areas,r.extraction),
  'semantic_status':r.semantic_status,'questionnaire_counts':r.counts,
  'questionnaire_results':[{'question_id':x.question_id,'status':x.status,'reason':x.reason,'missing_facts':list(x.missing_facts),'provenance':[{'filename':f.source_file,'locator':f.source_locator,'excerpt':f.snippet,'scope':f.scope,'report_type':f.report_type,'audit_period':f.audit_period,'authority':f.authority} for f in x.known_facts],'scoped_observations':x.scoped_observations,'context_sources':x.context_sources,'rejected_sources':x.rejected_sources,'conflict_details':x.conflict_details} for x in r.areas],
  'evidence_results':[{'filename':e.filename,'role':e.evidence_type,'state':e.state,'needs_review':e.needs_review} for e in r.evidence],
  'cross_artifact_findings':[{'code':o.code,'state':o.state,'detail':o.detail,'provenance':[{'filename':p.filename,'locator':p.locator,'excerpt':p.excerpt} for p in o.provenance]} for o in (g.observations if g else [])],
  'recovery_findings':[{'code':i.code,'state':i.state,'detail':i.detail,'provenance':[prov(p) for p in i.provenance]} for i in (r.recovery.issues if r.recovery else [])]
 }
 out=Path(a.output) if a.output else Path('artifacts')/f'run_pack_{root.name}.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,indent=2));print(json.dumps(payload,indent=2));print('output:',out)
if __name__=='__main__':main()
