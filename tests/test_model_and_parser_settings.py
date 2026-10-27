import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import fitz
import pytest

from src.api.routers import config as router
from src.api.routers import document_processing as document_router
from src.services import document_processing as docs
from src.services.config import unified_config as unified


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(unified, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(unified, "_config_manager", None)
    monkeypatch.setattr(unified.UnifiedConfigManager, "_instance", None)
    monkeypatch.setattr(docs, "SETTINGS_PATH", tmp_path / "documents.json")
    app = FastAPI()
    app.include_router(router.router, prefix="/config")
    app.include_router(document_router.router, prefix="/documents")
    return TestClient(app)


def test_saved_provider_test_uses_actual_key_and_edits_preserve_mask(client, monkeypatch):
    seen = {}

    async def fake_complete(**kwargs):
        seen.update(kwargs)
        return "Yes"

    monkeypatch.setattr(router, "llm_complete", fake_complete)
    response = client.post(
        "/config/llm",
        json={
            "name": "Self host",
            "provider": "vllm",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "local",
            "api_key": "test-private-key",
        },
    )
    assert response.status_code == 200
    assert response.json()["api_key"] == "***"
    config_id = response.json()["id"]
    assert client.post(f"/config/llm/{config_id}/test").json()["success"]
    assert seen["api_key"] == "test-private-key"
    edited_test = client.post("/config/llm/test", json={
        "provider": "vllm", "base_url": "http://127.0.0.1:8000/v1",
        "api_key": "", "model": "edited-model", "config_id": config_id,
    })
    assert edited_test.json()["success"]
    assert seen["api_key"] == "test-private-key"
    client.put(f"/config/llm/{config_id}", json={"api_key": "***", "name": "Renamed"})
    assert (
        unified.get_config_manager().get_config(unified.ConfigType.LLM, config_id)["api_key"]
        == "test-private-key"
    )


def test_huggingface_save_and_activate_wins_over_env(client, monkeypatch):
    from src.services.embedding.config import get_embedding_config

    monkeypatch.setenv("EMBEDDING_BINDING", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "env-model")
    response = client.post(
        "/config/embedding",
        json={
            "name": "Local HF",
            "provider": "huggingface",
            "model": "BAAI/bge-m3",
            "dimensions": 1024,
        },
    )
    assert response.status_code == 200, response.text
    config_id = response.json()["id"]
    assert client.post(f"/config/embedding/{config_id}/active").status_code == 200
    actual = get_embedding_config()
    assert actual.binding == "huggingface" and actual.model == "BAAI/bge-m3"
    assert actual.dim == 1024
    assert client.post("/config/embedding/default/active").status_code == 200
    assert get_embedding_config().model == "env-model"


def test_invalid_endpoint_and_dimensions_rejected(client):
    for payload in [
        {"base_url": "person@example.com", "dimensions": 4},
        {"base_url": "http://localhost:8000/v1", "dimensions": -1},
    ]:
        response = client.post(
            "/config/embedding",
            json={"name": "Bad", "provider": "vllm", "model": "test", **payload},
        )
        assert response.status_code == 422


def test_vllm_embedding_test_calls_real_local_http_and_checks_dimensions(client):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, payload))
            body = json.dumps(
                {"model": "served-model", "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = {
            "provider": "vllm",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "model": "served-model",
            "dimensions": 4,
        }
        assert client.post("/config/embedding/test", json=payload).json()["success"]
        assert seen[0][0] == "/v1/embeddings"
        payload["dimensions"] = 8
        assert not client.post("/config/embedding/test", json=payload).json()["success"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_huggingface_test_needs_neither_url_nor_key(client, monkeypatch):
    import numpy as np

    from src.services.embedding.adapters.huggingface_local import HuggingFaceLocalEmbeddingAdapter

    class FakeModel:
        def encode(self, texts, **kwargs):
            return np.ones((len(texts), 4))

    monkeypatch.setattr(
        HuggingFaceLocalEmbeddingAdapter,
        "_load_model",
        lambda self: setattr(self, "_model", FakeModel()),
    )
    result = client.post(
        "/config/embedding/test",
        json={"provider": "huggingface", "model": "fake-local", "dimensions": 4},
    )
    assert result.json()["success"], result.text


def pdf_bytes():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "RAG parser regression document")
    value = document.tobytes()
    document.close()
    return value


def test_document_settings_save_mask_preview_and_page_limit(client):
    assert len(client.get("/documents").json()["presets"]) >= 10
    response = client.put("/documents", json={"parser": "pymupdf", "api_key": "private-parser-key"})
    assert response.json()["config"]["api_key"] == "***"
    assert client.put("/documents", json={"parser": "pymupdf", "api_key": "***"}).status_code == 200
    assert docs.get_document_config().api_key == "private-parser-key"
    preview = client.post(
        "/documents/test", files={"file": ("sample.pdf", pdf_bytes(), "application/pdf")}
    )
    assert preview.status_code == 200, preview.text
    assert "regression document" in preview.json()["preview"]
    document = fitz.open()
    document.new_page()
    document.new_page()
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(
            docs.parse_document(
                _write_pdf(document),
                docs.SETTINGS_PATH.parent / "out",
                docs.DocumentProcessingConfig(max_pages=1),
            )
        )


def _write_pdf(document):
    path = docs.SETTINGS_PATH.parent / "two-pages.pdf"
    document.save(path)
    document.close()
    return path


def test_auto_never_calls_cloud_and_explicit_failure_is_reported(client, monkeypatch):
    calls = []

    async def fake_extract(parser, *args):
        calls.append(parser)
        if parser == "pymupdf":
            raise ValueError("scan")
        return [{"type": "text", "text": "OCR result", "page_idx": 0}], []

    monkeypatch.setattr(docs, "_extract", fake_extract)
    path = docs.SETTINGS_PATH.parent / "note.txt"
    path.write_text("test")
    result = asyncio.run(docs.parse_document(path, path.parent / "out"))
    assert result["parser"] == "mineru" and "llamaparse" not in calls
    assert result["warnings"]
    with pytest.raises(ValueError, match="scan"):
        asyncio.run(
            docs.parse_document(
                path, path.parent / "out", docs.DocumentProcessingConfig(parser="pymupdf")
            )
        )


def test_upload_stays_inside_raw_and_preserves_old_file_on_limit(tmp_path, monkeypatch):
    import io

    from fastapi import HTTPException
    from starlette.datastructures import UploadFile

    from src.api.routers.knowledge import save_uploaded_document
    from src.utils.document_validator import DocumentValidator

    raw = tmp_path / "raw"
    upload = UploadFile(io.BytesIO(b"safe"), filename="../note.txt")
    path = asyncio.run(save_uploaded_document(upload, raw))
    assert path == raw / "note.txt"
    assert not (tmp_path / "note.txt").exists()
    monkeypatch.setattr(DocumentValidator, "MAX_FILE_SIZE", 4)
    oversized = UploadFile(io.BytesIO(b"too-large"), filename="note.txt")
    with pytest.raises(HTTPException) as error:
        asyncio.run(save_uploaded_document(oversized, raw))
    assert error.value.status_code == 413
    assert path.read_bytes() == b"safe"
    assert sorted(x.name for x in raw.iterdir()) == ["note.txt"]


def test_mineru_v4_preserves_page_numbers(tmp_path, monkeypatch):
    import importlib.metadata
    import sys
    from types import ModuleType, SimpleNamespace

    pages = [SimpleNamespace(page_idx=0), SimpleNamespace(page_idx=3)]

    class Middle:
        def model_copy(self, update):
            return update

    class Result:
        def __init__(self, middle):
            self.middle = middle

        def markdown(self):
            return f"Page {self.middle['pages'][0].page_idx} text"

    async def parse(*args, **kwargs):
        assert kwargs['tier'] == 'flash'
        return SimpleNamespace(pages=pages, middle_json=Middle())

    sdk = ModuleType('mineru.parser')
    sdk.parse_async = parse
    sdk.ParseResult = Result
    sdk.MinerUApiParser = object
    monkeypatch.setitem(sys.modules, 'mineru.parser', sdk)
    monkeypatch.setattr(importlib.metadata, 'version', lambda name: '4.0.10')
    blocks, _ = asyncio.run(docs._extract('mineru', tmp_path / 'a.pdf', tmp_path, docs.DocumentProcessingConfig(parser='mineru', mineru_tier='flash')))
    assert [b['page_idx'] for b in blocks] == [0, 3]


def test_tts_connection_rejects_unreachable_endpoint(client):
    result = client.post('/config/tts/test', json={
        'provider': 'openai', 'base_url': 'http://127.0.0.1:1/v1',
        'api_key': 'offline', 'model': 'tts-1', 'voice': 'alloy',
    })
    assert result.status_code == 200
    assert result.json()['success'] is False


def test_llm_probe_rejects_empty_response(client, monkeypatch):
    async def empty(**kwargs):
        return ''
    monkeypatch.setattr(router, 'llm_complete', empty)
    response = client.post('/config/llm/test', json={
        'provider': 'vllm', 'base_url': 'http://localhost:8000/v1', 'model': 'local',
    })
    assert response.status_code == 200
    assert response.json()['success'] is False
    assert 'no answer text' in response.json()['message']


def test_llm_probe_returns_json_before_timeout(client, monkeypatch):
    async def slow(**kwargs):
        assert kwargs['max_retries'] == 0
        await asyncio.sleep(1)
        return 'late'
    monkeypatch.setattr(router, 'llm_complete', slow)
    monkeypatch.setattr(router, 'LLM_TEST_TIMEOUT_SECONDS', 0.01)
    response = client.post('/config/llm/test', json={
        'provider': 'vllm', 'base_url': 'http://localhost:8000/v1', 'model': 'local',
    })
    assert response.status_code == 200
    assert response.json()['success'] is False
    assert 'timed out' in response.json()['message']


def test_llm_probe_passes_full_transport_timeout(client, monkeypatch):
    async def completion(**kwargs):
        assert kwargs['timeout'] == 300
        assert kwargs['max_retries'] == 0
        return 'Yes'
    monkeypatch.setattr(router, 'llm_complete', completion)
    response = client.post('/config/llm/test', json={
        'provider':'vllm', 'base_url':'http://localhost:8000/v1', 'model':'local',
    })
    assert response.json()['success'] is True


def test_background_probe_polls_without_persisting_secrets(client, monkeypatch):
    import time
    async def slow(**kwargs):
        await asyncio.sleep(0.05)
        return 'Yes'
    monkeypatch.setattr(router, 'llm_complete', slow)
    monkeypatch.setattr(router, '_LLM_TESTS', {})
    with client as session:
        response=session.post('/config/llm/test?background=true',json={
            'provider':'vllm','base_url':'http://localhost:8000/v1','model':'local','api_key':'private-test-secret',
        })
        assert response.status_code == 200
        test_id=response.json()['test_id']
        assert 'private-test-secret' not in str(router._LLM_TESTS)
        for _ in range(100):
            state=session.get('/config/llm-tests/'+test_id).json()
            if state['status']=='completed':break
            time.sleep(0.01)
        assert state['result']['success']
        assert 'private-test-secret' not in str(state)


def test_background_probe_bounds_concurrency(client, monkeypatch):
    now=__import__('time').monotonic()
    monkeypatch.setattr(router,'_LLM_TESTS',{'a':{'status':'pending','created':now},'b':{'status':'pending','created':now}})
    response=client.post('/config/llm/test?background=true',json={'provider':'vllm','base_url':'http://localhost:8000/v1','model':'local'})
    assert response.status_code == 429


def test_expired_background_probe_is_removed(client, monkeypatch):
    monkeypatch.setattr(router,'_LLM_TESTS',{'old':{'status':'completed','created':0,'result':{'success':True}}})
    assert client.get('/config/llm-tests/old').status_code == 404
    assert 'old' not in router._LLM_TESTS
