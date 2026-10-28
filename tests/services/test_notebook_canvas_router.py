import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.services.notebook_canvas as canvas_module
from src.api.routers import notebook as notebook_router
from src.api.utils.notebook_manager import NotebookManager
from src.services.notebook_canvas import NotebookCanvasService


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9QmW2GYAAAAASUVORK5CYII="
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    manager = NotebookManager(base_dir=str(tmp_path / "notebook"))
    canvas_service = NotebookCanvasService(base_dir=tmp_path / "canvas")

    # Router-level dependency replacements.
    monkeypatch.setattr(notebook_router, "notebook_manager", manager)
    monkeypatch.setattr(notebook_router, "notebook_canvas_service", canvas_service)
    # Service-level manager used at commit stage.
    monkeypatch.setattr(canvas_module, "notebook_manager", manager)

    app = FastAPI()
    app.include_router(notebook_router.router, prefix="/api/v1/notebook")

    with TestClient(app) as test_client:
        yield test_client


def _create_notebook(client: TestClient) -> str:
    response = client.post(
        "/api/v1/notebook/create",
        json={"name": "Canvas Notebook", "description": "for tests"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    return payload["notebook"]["id"]


def _create_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/notebook/canvas/sessions",
        json={"title": "Canvas Session"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    return payload["session"]["session_id"]


def test_canvas_pipeline_process_confirm_commit_flow(client: TestClient):
    notebook_id = _create_notebook(client)
    session_id = _create_session(client)

    batch_response = client.post(
        f"/api/v1/notebook/canvas/sessions/{session_id}/strokes:batch",
        json={
            "page_index": 0,
            "strokes": [{"id": "s1", "points": [{"x": 10, "y": 20}]}],
            "dirty_regions": [{"x": 0, "y": 0, "w": 100, "h": 80}],
            "snapshot_data_url": PNG_DATA_URL,
            "replace_page": True,
        },
    )
    assert batch_response.status_code == 200
    assert batch_response.json()["success"] is True

    process_response = client.post(f"/api/v1/notebook/canvas/sessions/{session_id}/process")
    assert process_response.status_code == 200
    process_payload = process_response.json()
    assert process_payload["success"] is True
    blocks = process_payload["session"]["structured"]["blocks"]
    assert isinstance(blocks, list)
    assert len(blocks) >= 1

    updates = [
        {"id": block["id"], "text": "Confirmed OCR text", "block_type": "paragraph"}
        for block in blocks
    ]
    confirm_response = client.post(
        f"/api/v1/notebook/canvas/sessions/{session_id}/confirm",
        json={"block_updates": updates},
    )
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert confirm_payload["success"] is True
    assert confirm_payload["review_issues"] == []

    commit_response = client.post(
        f"/api/v1/notebook/canvas/sessions/{session_id}/commit",
        json={
            "notebook_id": notebook_id,
            "title": "Canvas Commit",
            "user_query": "Canvas test query",
        },
    )
    assert commit_response.status_code == 200
    commit_payload = commit_response.json()
    assert commit_payload["success"] is True
    assert commit_payload["record"]["type"] == "canvas"
    assert commit_payload["record"]["metadata"]["source"] == "advanced_canvas"

    notebook_response = client.get(f"/api/v1/notebook/{notebook_id}")
    assert notebook_response.status_code == 200
    notebook_payload = notebook_response.json()
    assert len(notebook_payload["records"]) == 1
    assert notebook_payload["records"][0]["type"] == "canvas"


def test_canvas_commit_requires_confirm_when_low_confidence(client: TestClient):
    notebook_id = _create_notebook(client)
    session_id = _create_session(client)

    client.post(
        f"/api/v1/notebook/canvas/sessions/{session_id}/strokes:batch",
        json={
            "page_index": 0,
            "strokes": [],
            "dirty_regions": [{"x": 0, "y": 0, "w": 50, "h": 40}],
            "snapshot_data_url": PNG_DATA_URL,
            "replace_page": True,
        },
    )
    process_response = client.post(f"/api/v1/notebook/canvas/sessions/{session_id}/process")
    assert process_response.status_code == 200

    commit_response = client.post(
        f"/api/v1/notebook/canvas/sessions/{session_id}/commit",
        json={
            "notebook_id": notebook_id,
            "title": "Should Fail",
            "user_query": "low confidence commit",
        },
    )
    assert commit_response.status_code == 400
    assert "low-confidence OCR blocks" in commit_response.json()["detail"]
