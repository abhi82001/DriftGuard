"""/health, friendly error pages and honest AI mode label (no API key needed)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from backend.src import app as appmod  # noqa: E402

client = TestClient(appmod.app, raise_server_exceptions=False)


def test_health_reports_ai_off_without_key(monkeypatch):
    monkeypatch.delenv("DRIFTGUARD_DEMO_MODE", raising=False)
    for name in ("ANTHROPIC_API_KEY", "DRIFTGUARD_AI_PROVIDER", "DRIFTGUARD_AI_MODEL",
                 "DRIFTGUARD_SEMANTIC_PROVIDER", "DRIFTGUARD_CLAUDE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["ai"]["ai_active"] is False
    assert set(body["ai"]["missing_config"]) == {"DRIFTGUARD_AI_PROVIDER", "DRIFTGUARD_AI_MODEL"}


def test_health_never_leaks_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-123")
    assert "sk-secret-123" not in client.get("/health").text


def test_browser_gets_html_error_and_api_gets_json():
    page = client.get("/nope", headers={"accept": "text/html"})
    assert page.status_code == 404 and "text/html" in page.headers["content-type"]
    api = client.get("/api/nope", headers={"accept": "application/json"})
    assert api.status_code == 404 and "error" in api.json()


def test_unhandled_error_is_generic(monkeypatch):
    def boom():
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(appmod, "health", boom, raising=False)

    @appmod.app.get("/__boom")
    def _boom():
        raise RuntimeError("secret internal detail")

    r = client.get("/__boom")
    assert r.status_code == 500 and "secret internal detail" not in r.text
