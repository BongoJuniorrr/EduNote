"""Regression tests for the single-user runtime (no account/token boundary)."""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.agents.chat.session_manager import SessionManager
from src.api.main import _validate_production_security, app
from src.api.routers import chat, jobs, knowledge, settings
from src.security.auth import LOCAL_USER, get_current_user, get_optional_current_user
from src.services.queue.job_store import PersistentJobStore


def test_identity_is_fixed_without_secrets(monkeypatch):
    monkeypatch.delenv("EDUNOTE_AUTH_SECRET", raising=False)
    monkeypatch.delenv("EDUNOTE_ADMIN_KEY", raising=False)
    assert asyncio.run(get_current_user()) == LOCAL_USER
    assert asyncio.run(get_optional_current_user()) == LOCAL_USER


def test_account_and_admin_routes_are_removed():
    client = TestClient(app)
    for path in ["/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/admin/users"]:
        assert client.post(path, json={}).status_code == 404
    assert client.get("/api/v1/providers").status_code == 404


def test_settings_and_historical_chat_sessions_need_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "interface.json")
    manager = SessionManager(tmp_path / "chat")
    first = manager.create_session("Before accounts")
    second = manager.create_session("Old account", owner_id="former-account")
    monkeypatch.setattr(chat, "session_manager", manager)
    client = TestClient(app)
    assert client.get("/api/v1/settings").status_code == 200
    updated = client.put("/api/v1/settings/theme", json={"theme": "dark"})
    assert updated.status_code == 200
    assert settings.load_ui_settings()["theme"] == "dark"
    for session in [first, second]:
        assert client.get(f"/api/v1/chat/sessions/{session['session_id']}").status_code == 200
    assert len(client.get("/api/v1/chat/sessions").json()) == 2


def test_websockets_work_without_token():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/chat") as ws:
        ws.send_json({"message": ""})
        assert ws.receive_json()["type"] == "error"
    with client.websocket_connect("/api/v1/solve"):
        pass
    with client.websocket_connect("/api/v1/question/generate"):
        pass


def test_jobs_use_local_workspace_and_allow_reading_legacy_jobs(tmp_path, monkeypatch):
    store = PersistentJobStore(tmp_path / "queue.sqlite3")
    monkeypatch.setattr(jobs, "get_job_store", lambda: store)
    old = store.enqueue("old-account", "test", {})
    client = TestClient(app)
    assert client.get(f"/api/v1/jobs/{old.id}").status_code == 200
    response = client.post("/api/v1/jobs", json={"kind": "test", "payload": {}})
    # Single-owner legacy jobs remain readable; new work must use typed routes.
    assert response.status_code == 422


def test_kb_query_and_provider_use_workspace_config(tmp_path, monkeypatch):
    config = SimpleNamespace(
        api_key="fake",
        base_url="https://example.test/v1",
        model="test",
        binding="openai",
        api_version=None,
    )
    monkeypatch.setattr(knowledge, "get_llm_config", lambda: config)
    monkeypatch.setattr(
        knowledge, "get_job_store", lambda: PersistentJobStore(tmp_path / "queue.sqlite3")
    )
    assert knowledge.get_workspace_llm_profile()["api_key"] == "fake"
    response = TestClient(app).post(
        "/api/v1/knowledge/query", json={"kb_name": "demo", "query": "hello"}
    )
    assert response.status_code == 202
    assert "llm_profile_id" not in response.json()["job"]["payload"]


def test_production_startup_does_not_require_accounts_or_worker(monkeypatch):
    monkeypatch.setenv("EDUNOTE_ENV", "production")
    monkeypatch.setenv("EDUNOTE_QUEUE_WORKER_ENABLED", "false")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3782")
    monkeypatch.delenv("EDUNOTE_AUTH_SECRET", raising=False)
    monkeypatch.delenv("EDUNOTE_ADMIN_KEY", raising=False)
    _validate_production_security()


def test_settings_secrets_are_not_static_outputs():
    assert TestClient(app).get("/api/outputs/settings/llm_configs.json").status_code == 404
