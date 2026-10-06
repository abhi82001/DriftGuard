"""Offline, read-only regression runner for the supplied synthetic evidence pack."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend' / 'src'))
from ingestion import extract, IngestionError
from evidence.pipeline import analyze_evidence_file
from evidence.tabular import is_tabular
from assessment import MvpKnowledge
from documents import DocumentAnalyzer

def run(pack: Path):
    files = sorted(p for p in pack.rglob('*') if p.is_file() and p.name != 'MANIFEST.csv')
    results, documents = [], []
    for p in files:
        raw = p.read_bytes()
        row = {'file': str(p.relative_to(pack)), 'bytes': len(raw)}
        try:
            d = extract(p.name, raw)
            documents.append(d)
            row.update(ingestion='OK', chunks=len(d.chunks))
        except IngestionError as e:
            row.update(ingestion='ERROR', issue=str(e))
        if is_tabular(p.name):
            q = analyze_evidence_file(p.name, raw)
            row.update(qa_type=q.evidence_type, qa_state=q.state, qa_checks=len(q.checks))
            if q.evidence_type == 'UNCLASSIFIED':
                row['qa_issue'] = 'EQA-UNSUPPORTED-TYPE: No applicable structured validator; NOT a QA pass'
        results.append(row)
    assessment = DocumentAnalyzer(MvpKnowledge()).analyze('synthetic pack', documents, [], False)
    report = {'files': len(files), 'ingestion': dict(Counter(r['ingestion'] for r in results)),
              'tabular_qa': dict(Counter(r.get('qa_type') for r in results if 'qa_type' in r)),
              'questionnaire_counts': assessment.counts, 'claims': len(assessment.claims),
              'established': [{'question': a.question_id, 'sources': [f.source_file + ':' + f.source_locator for f in a.known_facts]} for a in assessment.areas if a.status == 'ESTABLISHED'],
              'files_detail': results,
              'note': 'Offline diagnostic across the entire pack. Web upload is bounded to 10 files per request. These are preliminary deterministic claims, not an audit opinion.'}
    (ROOT / 'ORIGINAL_PACK_RUN_RESULTS.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'files_detail'}, indent=2))
    return report
if __name__ == '__main__':
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'original_pack' / 'driftguard_soc2_test_pack')
