"""Upload page shows a full-page analysing overlay instead of an unchanged form."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402


def test_index_has_busy_overlay_wired_to_both_forms():
    html = TestClient(app_module.app).get("/").text
    assert 'id="busy-overlay"' in html
    assert html.count("<form ") >= 2 and html.count(" data-busy>") == 2
    for stage in ("Reading files", "Extracting facts", "Mapping to questions"):
        assert stage in html
    assert "ingestion-progress" not in html
