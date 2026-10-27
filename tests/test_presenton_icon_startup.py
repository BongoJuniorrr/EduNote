import asyncio
import importlib.util
import json
from pathlib import Path


def service(tmp_path, monkeypatch):
    monkeypatch.delenv("PRESENTON_SEMANTIC_ICONS", raising=False)
    path = Path(__file__).resolve().parents[1] / "presenton/servers/fastapi/services/icon_finder_service.py"
    spec = importlib.util.spec_from_file_location("isolated_icon_service", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = tmp_path / "icons.json"
    data.write_text(json.dumps({"icons": [
        {"name": "book-open-bold", "tags": ["books", "reading", "learn"]},
        {"name": "airplane-bold", "tags": ["flight", "travel"]},
        {"name": "book-thin", "tags": ["book"]},
    ]}))
    return module.IconFinderService(data)


def test_fresh_icon_service_does_not_initialize_model(tmp_path, monkeypatch):
    instance = service(tmp_path, monkeypatch)
    assert instance._icons is None
    assert instance._collection is None
    monkeypatch.setattr(instance, "_semantic_search", lambda *args: (_ for _ in ()).throw(AssertionError("Model must remain unused")))
    assert asyncio.run(instance.search_icons("reading books")) == ["/static/icons/bold/book-open-bold.svg"]


def test_concurrent_keyword_queries_work_without_downloads(tmp_path, monkeypatch):
    instance = service(tmp_path, monkeypatch)

    async def run():
        return await asyncio.gather(instance.search_icons("books"), instance.search_icons("flight"))

    assert asyncio.run(run()) == [["/static/icons/bold/book-open-bold.svg"], ["/static/icons/bold/airplane-bold.svg"]]


def test_optional_model_failure_falls_back_without_logging_details(tmp_path, monkeypatch, caplog):
    instance = service(tmp_path, monkeypatch)
    monkeypatch.setenv("PRESENTON_SEMANTIC_ICONS", "true")

    def unavailable(*args):
        raise RuntimeError("private-provider-detail")

    monkeypatch.setattr(instance, "_semantic_search", unavailable)
    assert asyncio.run(instance.search_icons("books")) == ["/static/icons/bold/book-open-bold.svg"]
    assert "private-provider-detail" not in caplog.text
