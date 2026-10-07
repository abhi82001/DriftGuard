from __future__ import annotations

import sqlite3
import pytest

from driftguard_platform.config import PlatformConfig
from driftguard_platform.persistence import create_storage, registry as storage_registry
from driftguard_platform.persistence.contracts import UnsupportedStorageProvider
from driftguard_platform.secrets import create_secret_provider
from driftguard_platform.secrets.contracts import SecretError


def test_platform_config_selects_infrastructure_without_domain_changes(monkeypatch):
    monkeypatch.setenv("DRIFTGUARD_STORAGE_PROVIDER", "sqlite")
    monkeypatch.setenv("DRIFTGUARD_DATABASE_URL", "sqlite:///example.db")
    monkeypatch.setenv("DRIFTGUARD_SECRET_PROVIDER", "env")
    cfg = PlatformConfig.from_env()
    assert cfg.storage_provider == "sqlite"
    assert cfg.storage_url == "sqlite:///example.db"
    assert cfg.secret_provider == "env"


def test_sqlite_storage_contract_initializes_and_healthchecks(tmp_path):
    provider = create_storage(PlatformConfig(storage_provider="sqlite", storage_url=str(tmp_path / "dg.db")))
    assert provider.name == "sqlite"
    assert provider.healthcheck() is True
    con = provider.connect()
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    assert {"users", "sessions", "saved"} <= tables


def test_storage_registry_accepts_future_provider_without_core_change():
    class FakeProvider:
        name = "futuredb"
        def initialize(self): pass
        def connect(self): return object()
        def connection(self): raise NotImplementedError
        def healthcheck(self): return True
    storage_registry.register("futuredb", lambda **_: FakeProvider())
    provider = create_storage(PlatformConfig(storage_provider="futuredb"))
    assert provider.name == "futuredb"
    assert provider.healthcheck()


def test_unknown_storage_provider_fails_closed():
    with pytest.raises(UnsupportedStorageProvider):
        create_storage(PlatformConfig(storage_provider="made-up-db"))


def test_environment_secret_provider_resolves_reference_not_literal_secret(monkeypatch):
    monkeypatch.setenv("DG_TEST_SECRET", "super-secret-value")
    provider = create_secret_provider(PlatformConfig(secret_provider="env"))
    assert provider.get("DG_TEST_SECRET") == "super-secret-value"
    with pytest.raises(SecretError):
        provider.get("DG_MISSING_SECRET")


def test_connector_config_resolves_secret_reference_without_storing_secret(monkeypatch):
    from driftguard_platform.integrations import ConnectorConfig, connector_for, ConnectorRegistry
    from driftguard_platform.secrets import create_secret_provider
    monkeypatch.setenv("OKTA_TEST_TOKEN", "token-value")
    captured = {}
    class FakeConnector:
        name = "fake"
        def test_connection(self): return True
        def collect(self, cursor=None): raise NotImplementedError
    registry = ConnectorRegistry()
    registry.register("fake", lambda **kw: captured.update(kw) or FakeConnector())
    cfg = ConnectorConfig("fake", settings={"base_url": "https://example.test"}, secret_refs={"token": "OKTA_TEST_TOKEN"})
    connector = connector_for(cfg, secret_provider=create_secret_provider(PlatformConfig(secret_provider="env")), connector_registry=registry)
    assert connector.name == "fake"
    assert captured == {"base_url": "https://example.test", "token": "token-value"}
    assert "token-value" not in repr(cfg)


def test_ai_provider_config_uses_secret_reference(monkeypatch):
    from driftguard_platform.ai import AIRegistry
    from driftguard_platform.byoai import AIProviderConfig, provider_from_references
    from driftguard_platform.secrets import create_secret_provider
    monkeypatch.setenv("AI_TEST_KEY", "ai-secret")
    captured = {}
    class FakeAI:
        name = "fake-ai"
        def execute(self, request): raise NotImplementedError
    registry = AIRegistry()
    registry.register("fake-ai", lambda **kw: captured.update(kw) or FakeAI())
    cfg = AIProviderConfig("fake-ai", model="model-x", secret_refs={"api_key": "AI_TEST_KEY"})
    provider = provider_from_references(cfg, registry, create_secret_provider(PlatformConfig(secret_provider="env")))
    assert provider.name == "fake-ai"
    assert captured == {"api_key": "ai-secret", "model": "model-x"}
    assert "ai-secret" not in repr(cfg)


def test_account_repository_contract_hides_sqlite_from_application(tmp_path):
    from driftguard_platform.persistence.repositories import create_account_repository
    from driftguard_platform.persistence.accounts import DuplicateUserError
    cfg = PlatformConfig(storage_provider="sqlite", storage_url=str(tmp_path / "accounts.db"))
    repo = create_account_repository(cfg)
    uid = repo.create_user("user@example.test", "hash")
    assert repo.find_user("user@example.test") == (uid, "hash")
    repo.replace_session(uid, "token", "9999-01-01T00:00:00+00:00")
    assert repo.user_for_session("token", "2026-01-01T00:00:00+00:00") == uid
    repo.save_bounded(uid, "doc-results", "aid", "Vendor", '{"ok":true}')
    assert repo.saved_exists(uid, "doc-results", "aid")
    assert repo.load_saved(uid, "doc-results", "aid") == '{"ok":true}'
    assert repo.list_saved(uid)[0].aid == "aid"
    with pytest.raises(DuplicateUserError):
        repo.create_user("user@example.test", "other")
