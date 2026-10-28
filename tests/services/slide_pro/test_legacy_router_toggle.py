import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi.testclient import TestClient


def _build_client(monkeypatch: pytest.MonkeyPatch, *, legacy_enabled: bool) -> TestClient:
    monkeypatch.setenv(
        "ENABLE_LEGACY_SLIDE_PRO", "true" if legacy_enabled else "false"
    )
    monkeypatch.setenv("EMBEDDING_PREWARM", "false")

    import src.api.main as api_main

    api_main = importlib.reload(api_main)
    return TestClient(api_main.app)


def test_slide_pro_router_returns_404_when_legacy_disabled(monkeypatch: pytest.MonkeyPatch):
    with _build_client(monkeypatch, legacy_enabled=False) as client:
        response = client.get("/api/v1/slide-pro/templates")
    assert response.status_code == 404


def test_slide_pro_router_is_available_when_legacy_enabled(monkeypatch: pytest.MonkeyPatch):
    with _build_client(monkeypatch, legacy_enabled=True) as client:
        response = client.get("/api/v1/slide-pro/templates")
    assert response.status_code == 200
