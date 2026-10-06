import io, logging, sys, time, zipfile
from pathlib import Path
import pytest
SRC=Path(__file__).resolve().parent.parent/'src'; sys.path.insert(0,str(SRC))
from production_hardening import BoundedAssessmentStore, neutralize_formula, safe_event
from upload_security import validate_file
from fastapi import HTTPException
from ingestion import extract_many

def test_formula_injection_is_neutralized(): assert neutralize_formula('=CMD()').startswith("'=")
def test_formula_prefixes_are_all_neutralized(): assert all(neutralize_formula(x).startswith("'") for x in ['+1','-1','@SUM(A1)'])
def test_normal_text_unchanged(): assert neutralize_formula('prod-db')=='prod-db'
def test_path_traversal_rejected():
    with pytest.raises(HTTPException): validate_file('../secret.txt',b'x')
def test_fake_pdf_rejected():
    with pytest.raises(HTTPException): validate_file('x.pdf',b'not pdf')
def test_active_office_content_rejected():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('word/document.xml','x');z.writestr('word/vbaProject.bin','x')
    with pytest.raises(HTTPException): validate_file('x.docx',b.getvalue())
def test_external_office_link_rejected():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('xl/workbook.xml','x');z.writestr('xl/externalLinks/externalLink1.xml','x')
    with pytest.raises(HTTPException): validate_file('x.xlsx',b.getvalue())
def test_store_is_bounded():
    s=BoundedAssessmentStore(max_items=2);s['a']=1;s['b']=2;s['c']=3;assert len(s)==2 and s.get('a') is None
def test_store_ttl_cleanup():
    s=BoundedAssessmentStore(ttl_seconds=0);s['a']=1;assert s.get('a') is None
def test_safe_logging_does_not_emit_evidence(caplog):
    with caplog.at_level(logging.INFO,logger='driftguard.ops'):safe_event('x',assessment_id='a',excerpt='TOP SECRET',content='SECRET')
    assert 'TOP SECRET' not in caplog.text and 'SECRET' not in caplog.text and 'assessment_id=a' in caplog.text
def test_one_bad_document_does_not_destroy_batch():
    docs,errors=extract_many([('good.txt',b'MFA is required.'),('bad.pdf',b'not pdf')]);assert len(docs)==1 and len(errors)==1
