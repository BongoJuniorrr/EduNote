"""Real LlamaIndex persistence/retrieval with deterministic offline embeddings."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("llama_index.core")

from src.services.rag.pipelines import llamaindex as module
from src.services import document_processing as docs


def test_index_retrieve_increment_and_embedding_change(tmp_path, monkeypatch):
    cfg = SimpleNamespace(model="offline-orchid", binding="test", dim=2, base_url="")

    class OfflineEmbedding:
        async def embed(self, texts, input_type=None):
            return [
                [float(text.lower().count("orchid")), float(text.lower().count("tensor"))]
                for text in texts
            ]

    monkeypatch.setattr(module, "get_embedding_config", lambda: cfg)
    monkeypatch.setattr(module, "get_embedding_client", lambda: OfflineEmbedding())
    monkeypatch.setattr(docs, "SETTINGS_PATH", tmp_path / "parser.json")
    orchid = tmp_path / "orchid.txt"
    orchid.write_text("An orchid is a flowering plant. Orchid roots absorb moisture.")
    tensor = tmp_path / "tensor.txt"
    tensor.write_text(
        "A tensor represents multidimensional arrays. Tensor operations power neural networks."
    )
    pipeline = module.LlamaIndexPipeline(str(tmp_path / "kbs"))
    assert asyncio.run(pipeline.initialize("demo", [str(orchid), str(tensor)]))
    result = asyncio.run(pipeline.search("orchid", "demo", top_k=1))
    assert "flowering plant" in result["content"], result
    assert result["sources"][0]["file_name"] == "orchid.txt"
    extra = tmp_path / "extra.txt"
    extra.write_text("Orchid flowers may attract bees.")
    assert asyncio.run(pipeline.add_documents("demo", [str(extra)]))
    cfg.model = "different-embedding"
    with pytest.raises(ValueError, match="Reindex"):
        asyncio.run(pipeline.search("orchid", "demo"))
    with pytest.raises(ValueError, match="Reindex"):
        asyncio.run(pipeline.add_documents("demo", [str(extra)]))
