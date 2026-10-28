import json

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import slide_pro as slide_router


def _sample_deck() -> dict:
    return {
        "version": "1.0",
        "deck_id": "",
        "meta": {
            "title": "Sample Deck",
            "language": "en",
            "template_id": "academic_evidence",
            "learning_goals": ["Goal 1"],
        },
        "size": {"width": 1600, "height": 900},
        "theme": {
            "palette": {
                "background": "#F8FAFC",
                "foreground": "#0F172A",
                "accent": "#0284C7",
                "muted": "#334155",
            },
            "fonts": {"title": "Sora", "body": "IBM Plex Sans"},
        },
        "slides": [
            {
                "id": "s1",
                "title": "Slide 1",
                "notes": "notes",
                "elements": [
                    {
                        "id": "e1",
                        "type": "text",
                        "box": {"x": 100, "y": 80, "w": 700, "h": 120, "rot": 0},
                        "style": {"fontSize": 42, "fontWeight": 700, "color": "#0F172A"},
                        "content": "Hello",
                    }
                ],
                "critic": {"density": 0.4, "readability": 0.9, "issues": []},
            }
        ],
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SLIDE_PRO_OUTPUT_DIR", str(tmp_path / "slide-pro"))

    async def fake_generate(*, title, language, source_text, source_records, instructions, settings):
        return {
            "deck_json": _sample_deck(),
            "plan": {
                "learning_goals": ["Goal 1"],
                "slides": [{"title": "Slide 1", "objective": "Obj", "key_points": ["P1"]}],
                "source": "fallback",
            },
            "critic_issues": [],
            "suggested_patches": [],
            "quality_checks": [{"name": "planner", "status": "warn", "detail": "fallback"}],
            "warnings": [],
        }

    def fake_run_critic(deck_json):
        return {
            "deck_json": deck_json,
            "issues": [{"slide_id": "s1", "issues": ["High visual density"]}],
            "suggested_patches": [
                {
                    "op": "suggest",
                    "slide_id": "s1",
                    "action": "reduce_density",
                    "value": {"target_density": 0.72},
                }
            ],
        }

    monkeypatch.setattr(slide_router.slide_pro_engine, "generate", fake_generate)
    monkeypatch.setattr(slide_router.slide_pro_engine, "run_critic", fake_run_critic)

    app = FastAPI()
    app.include_router(slide_router.router, prefix="/api/v1/slide-pro")

    with TestClient(app) as test_client:
        yield test_client


def test_slide_pro_templates_endpoint(client: TestClient):
    response = client.get("/api/v1/slide-pro/templates")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("templates"), list)
    assert any(item.get("id") == "academic_evidence" for item in payload["templates"])


def test_slide_pro_generate_returns_run_and_deck(client: TestClient):
    response = client.post(
        "/api/v1/slide-pro/generate",
        json={
            "title": "Test Deck",
            "language": "en",
            "source_text": "source",
            "instructions": "instructions",
            "settings": {"slide_count": 6, "template_id": "academic_evidence"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["run_id"].startswith("sp_")
    assert payload["deck_json"]["deck_id"] == payload["run_id"]
    assert payload["deck_json"]["meta"]["template_id"] == "academic_evidence"


def test_slide_pro_critic_returns_issues(client: TestClient):
    response = client.post("/api/v1/slide-pro/critic", json={"deck_json": _sample_deck()})
    assert response.status_code == 200
    payload = response.json()
    assert payload["issues"][0]["slide_id"] == "s1"
    assert payload["suggested_patches"][0]["action"] == "reduce_density"


def test_slide_pro_artifact_upload_and_get_run(client: TestClient):
    generated = client.post(
        "/api/v1/slide-pro/generate",
        json={
            "title": "Artifacts",
            "language": "en",
            "source_text": "",
            "instructions": "",
            "settings": {},
        },
    )
    assert generated.status_code == 200
    run_id = generated.json()["run_id"]

    upload = client.post(
        f"/api/v1/slide-pro/runs/{run_id}/artifacts",
        data={"manifest": json.dumps({"kind": "test"})},
        files=[("files", ("deck.slidepro.json", b"{}", "application/json"))],
    )
    assert upload.status_code == 200
    upload_payload = upload.json()
    assert upload_payload["success"] is True
    assert any(item["file_name"].endswith(".json") for item in upload_payload["artifacts"])

    run_response = client.get(f"/api/v1/slide-pro/runs/{run_id}")
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["success"] is True
    assert run_payload["run_id"] == run_id
    assert any(item["file_name"].endswith(".json") for item in run_payload["artifacts"])


def test_slide_pro_artifact_upload_rejects_invalid_extension(client: TestClient):
    generated = client.post(
        "/api/v1/slide-pro/generate",
        json={
            "title": "Invalid Artifact",
            "language": "en",
            "source_text": "",
            "instructions": "",
            "settings": {},
        },
    )
    assert generated.status_code == 200
    run_id = generated.json()["run_id"]

    upload = client.post(
        f"/api/v1/slide-pro/runs/{run_id}/artifacts",
        files=[("files", ("notes.txt", b"not allowed", "text/plain"))],
    )
    assert upload.status_code == 400
    assert "Allowed extensions" in upload.json()["detail"]
