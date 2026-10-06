import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ingestion import extract, IngestionError

def test_json_upload_preserves_source_paths():
    doc = extract('MFA_Enforcement_Config.json', json.dumps({'policies':[{'name':'production', 'enabled':True}]}).encode())
    assert any(c.locator == '$.policies[0].enabled' and 'True' in c.text for c in doc.chunks)

def test_invalid_json_is_not_silently_accepted():
    import pytest
    with pytest.raises(IngestionError, match='invalid JSON'):
        extract('bad.json', b'{bad')
