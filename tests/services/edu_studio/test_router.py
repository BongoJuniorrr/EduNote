import pytest
import json

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import edu_studio as edu_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDUSTUDIO_OUTPUT_DIR", str(tmp_path / "edu-studio"))

    monkeypatch.setattr(
        edu_router,
        "_resolve_llm_config",
        lambda _model_config_id: {
            "api_key": "test-key",
            "base_url": "http://localhost:8000/v1",
            "api_version": None,
            "model": "test-model",
            "provider": "openai",
        },
    )

    async def fake_run_workflow(self, workflow, payload):
        if workflow == "slide_deck":
            structured = {
                "deck_theme": {
                    "palette": {
                        "background": "#fff",
                        "foreground": "#111",
                        "accent": "#0ea5e9",
                        "muted": "#64748b",
                    },
                    "typography": {
                        "font_family": "Inter",
                        "title_scale": "2rem",
                        "body_scale": "1rem",
                    },
                    "visual_style": "clean-academic",
                    "ratio": "16:9",
                },
                "slides": [
                    {
                        "title": "Slide 1",
                        "objective": "Obj",
                        "key_points": ["Point"],
                        "activity": "Discuss",
                        "speaker_notes": "Notes",
                        "layout_hint": "bullets",
                        "visual_hint": "icon-set:education",
                    }
                ],
                "design_guidelines": ["Guideline"],
                "assessment_checkpoints": ["Checkpoint"],
            }
        else:
            structured = {"content": ["ok"]}

        return {
            "workflow": workflow,
            "title": payload.get("title") or workflow,
            "summary": "summary",
            "deliverable_markdown": "# Output",
            "structured_data": structured,
            "quality_checks": [],
            "next_actions": ["next"],
            "metadata": {"model": "test-model", "provider": "openai"},
        }

    monkeypatch.setattr(edu_router.EduStudioWorkflowAgent, "run_workflow", fake_run_workflow)

    app = FastAPI()
    app.include_router(edu_router.router, prefix="/api/v1/edu-studio")

    with TestClient(app) as test_client:
        yield test_client


def _create_run(client: TestClient, workflow: str = "slide_deck") -> dict:
    response = client.post(
        "/api/v1/edu-studio/run",
        json={
            "workflow": workflow,
            "title": "Test Run",
            "language": "en",
            "source_text": "Source",
            "instructions": "Instructions",
            "settings": {"slide_count": 3},
        },
    )
    assert response.status_code == 200
    return response.json()


def test_run_returns_run_id_and_artifact_metadata(client: TestClient):
    payload = _create_run(client, workflow="slide_deck")

    assert payload["success"] is True
    assert payload["run_id"].startswith("edu_")
    assert payload["artifact_base_url"].endswith(f"/{payload['run_id']}/artifacts")
    assert payload["artifacts"] == []
    assert payload["result"]["title"] == "Test Run"


def test_templates_endpoint_returns_workflow_catalog(client: TestClient):
    response = client.get("/api/v1/edu-studio/templates")
    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload.get("workflows"), list)
    assert any(item.get("id") == "slide_deck" for item in payload["workflows"])

    slide_config = next(item for item in payload["workflows"] if item.get("id") == "slide_deck")
    assert isinstance(slide_config.get("templates"), list)
    assert any(template.get("id") == "professional_lecture" for template in slide_config["templates"])


def test_run_with_files_parses_material_and_returns_run_info(client: TestClient):
    req = {
        "workflow": "lesson_plan",
        "title": "With File",
        "language": "en",
        "source_text": "",
        "instructions": "Use files",
        "settings": {"duration_minutes": 45},
    }

    response = client.post(
        "/api/v1/edu-studio/run-with-files",
        data={"payload": json.dumps(req)},
        files=[("files", ("lesson.txt", b"Lesson objective text", "text/plain"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["run_id"].startswith("edu_")
    assert len(payload["parsed_materials"]) == 1
    assert payload["parsed_materials"][0]["filename"] == "lesson.txt"
    assert payload["parsed_materials"][0]["content_length"] > 0


def test_artifact_upload_and_get_run_metadata(client: TestClient):
    run_payload = _create_run(client)
    run_id = run_payload["run_id"]

    upload_response = client.post(
        f"/api/v1/edu-studio/runs/{run_id}/artifacts",
        data={"manifest": json.dumps({"source": "e2e-test"})},
        files=[
            (
                "files",
                ("slide_01.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
            )
        ],
    )

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["success"] is True
    assert upload_payload["run_id"] == run_id
    assert any(item["file_name"].endswith(".png") for item in upload_payload["artifacts"])

    run_response = client.get(f"/api/v1/edu-studio/runs/{run_id}")
    assert run_response.status_code == 200
    run_info = run_response.json()
    assert run_info["run_id"] == run_id
    assert run_info["workflow"] == "slide_deck"
    assert isinstance(run_info["artifacts"], list)
    assert any(item["file_name"].endswith(".png") for item in run_info["artifacts"])


def test_artifact_upload_rejects_invalid_extension(client: TestClient):
    run_payload = _create_run(client)
    run_id = run_payload["run_id"]

    response = client.post(
        f"/api/v1/edu-studio/runs/{run_id}/artifacts",
        files=[("files", ("notes.txt", b"not allowed", "text/plain"))],
    )

    assert response.status_code == 400
    assert "Allowed extensions" in response.json()["detail"]


def test_run_uses_local_kb_fallback_when_rag_runtime_unavailable(client: TestClient, monkeypatch):
    async def fake_rag_search(*args, **kwargs):
        raise Exception(
            "RAG search failed: No LightRAG instance available. "
            "Please process documents first or provide a pre-initialized LightRAG instance."
        )

    monkeypatch.setattr(edu_router, "rag_search", fake_rag_search)
    monkeypatch.setattr(
        edu_router,
        "_get_kb_runtime_status",
        lambda _kb_name: {
            "exists": True,
            "status": "ready",
            "rag_initialized": False,
            "rag_provider": "vgu_course",
        },
    )
    monkeypatch.setattr(
        edu_router,
        "_local_kb_context_search",
        lambda kb_name, query, max_blocks=2: (
            f"Local KB excerpts:\n- [{kb_name}] Evidence for query: {query[:24]}"
        ),
    )

    response = client.post(
        "/api/v1/edu-studio/run",
        json={
            "workflow": "slide_deck",
            "title": "RAG fallback test",
            "language": "en",
            "source_text": "Source",
            "instructions": "Instructions",
            "settings": {"slide_count": 3},
            "context_enrichment": {
                "enable_rag": True,
                "kb_name": "Exploring CS",
                "rag_mode": "hybrid",
                "enable_web_search": False,
                "search_mode": "balanced",
                "search_provider": "",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    rag_meta = payload["context_enrichment"]["rag"]

    assert rag_meta["enabled"] is True
    assert rag_meta["fallback_hit_count"] >= 1
    assert rag_meta["hit_count"] == 0
    assert any("fallback excerpts" in warning.lower() for warning in payload["warnings"])


def test_run_marks_generation_fallback_when_rag_returns_retrieval_fallback(
    client: TestClient,
    monkeypatch,
):
    async def fake_rag_search(*args, **kwargs):
        return {
            "query": kwargs.get("query", ""),
            "answer": "Retrieved answer",
            "content": "Retrieved answer",
            "mode": "hybrid",
            "provider": "vgu_course",
            "metadata": {"answer_source": "retrieval_fallback"},
        }

    monkeypatch.setattr(edu_router, "rag_search", fake_rag_search)
    monkeypatch.setattr(
        edu_router,
        "_get_kb_runtime_status",
        lambda _kb_name: {
            "exists": True,
            "status": "ready",
            "rag_initialized": True,
            "rag_provider": "vgu_course",
        },
    )

    response = client.post(
        "/api/v1/edu-studio/run",
        json={
            "workflow": "slide_deck",
            "title": "RAG generation fallback",
            "language": "en",
            "source_text": "Source",
            "instructions": "Instructions",
            "settings": {"slide_count": 3},
            "context_enrichment": {
                "enable_rag": True,
                "kb_name": "Exploring CS",
                "rag_mode": "hybrid",
                "enable_web_search": False,
                "search_mode": "balanced",
                "search_provider": "",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    rag_meta = payload["context_enrichment"]["rag"]

    assert rag_meta["hit_count"] >= 1
    assert rag_meta["generation_fallback_count"] >= 1
    assert any("generation fallback was used" in warning.lower() for warning in payload["warnings"])


def test_rate_limit_is_json_429_not_internal_server_error(client, monkeypatch):
    from src.services.llm.exceptions import LLMRateLimitError

    async def limited(self, workflow, payload):
        raise LLMRateLimitError('quota reached', provider='test')

    monkeypatch.setattr(edu_router.EduStudioWorkflowAgent, 'run_workflow', limited)
    response = client.post('/api/v1/edu-studio/run', json={'workflow': 'lesson_plan', 'source_text': 'Source'})
    assert response.status_code == 429
    assert 'quota' in response.json()['detail']


def test_workflow_timeout_returns_json(client, monkeypatch):
    import asyncio
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(edu_router, '_run_workflow', slow)
    monkeypatch.setattr(edu_router, 'WORKFLOW_TIMEOUT_SECONDS', .01)
    response = client.post('/api/v1/edu-studio/run', json={'workflow':'lesson_plan'})
    assert response.status_code == 504
    assert 'timed out' in response.json()['detail']


def test_upload_is_bounded_before_parsing(client, monkeypatch):
    monkeypatch.setattr(edu_router, 'MAX_UPLOAD_BYTES', 4)
    response = client.post('/api/v1/edu-studio/run-with-files',
        data={'payload': json.dumps({'workflow':'lesson_plan'})},
        files={'files':('large.txt',b'12345','text/plain')})
    assert response.status_code == 413
