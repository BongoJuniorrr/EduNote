import asyncio

from src.services.rag.pipelines.vgu_course import VGUChunk, VGUCoursePipeline, VGUSectionSummary


def _sample_chunk() -> VGUChunk:
    return VGUChunk(
        chunk_id="c1",
        content="sample content",
        doc_id="d1",
        doc_name="doc.pdf",
        page_start=1,
        page_end=1,
        section_path="1.1",
    )


def _sample_section() -> VGUSectionSummary:
    return VGUSectionSummary(
        section_id="s1",
        doc_id="d1",
        doc_name="doc.pdf",
        section_path="1",
        summary="sample summary",
        page_start=1,
        page_end=2,
        chunk_ids=["c1"],
    )


def test_rerank_chunks_propagates_runtime_flag(monkeypatch):
    pipeline = VGUCoursePipeline(enable_reranker=False)
    chunk = _sample_chunk()
    captured: dict[str, object] = {}

    class DummyReranker:
        def predict(self, pairs):
            return [1.0 for _ in pairs]

    def fake_get_reranker(force_enable=None):
        captured["force_enable"] = force_enable
        return DummyReranker()

    monkeypatch.setattr(pipeline, "_get_reranker", fake_get_reranker)
    ranked = pipeline._rerank_chunks("query", [chunk], top_k=1, enable_reranker=True)

    assert captured["force_enable"] is True
    assert ranked[0].chunk_id == "c1"


def test_search_passes_runtime_reranker_flag(monkeypatch):
    pipeline = VGUCoursePipeline(
        enable_reranker=False,
        enable_query_expansion=False,
        enable_hybrid_search=False,
    )
    chunk = _sample_chunk()
    section = _sample_section()
    captured: dict[str, object] = {}

    async def fake_load_vgu_index(_kb_name):
        return [chunk], [section]

    async def fake_coarse_search(*args, **kwargs):
        return ["s1"]

    def fake_filter_chunks(*args, **kwargs):
        return [chunk]

    async def fake_semantic_search(*args, **kwargs):
        return [chunk]

    def fake_rerank_chunks(query, chunks, top_k, enable_reranker=None):
        captured["enable_reranker"] = enable_reranker
        return chunks[:top_k]

    monkeypatch.setattr(pipeline, "_load_vgu_index", fake_load_vgu_index)
    monkeypatch.setattr(pipeline, "_coarse_search", fake_coarse_search)
    monkeypatch.setattr(pipeline, "_filter_chunks_by_sections", fake_filter_chunks)
    monkeypatch.setattr(pipeline, "_semantic_search", fake_semantic_search)
    monkeypatch.setattr(pipeline, "_rerank_chunks", fake_rerank_chunks)

    result = asyncio.run(
        pipeline.search(
            query="query",
            kb_name="kb",
            mode="hybrid",
            only_need_context=True,
            enable_reranker=True,
            enable_query_expansion=False,
            enable_hybrid_search=False,
            coarse_top_k=1,
            fine_top_k=1,
            final_top_k=1,
        )
    )

    assert captured["enable_reranker"] is True
    assert result["provider"] == "vgu_course"


def test_search_degrades_to_retrieval_fallback_when_lightrag_fails(monkeypatch):
    pipeline = VGUCoursePipeline(
        enable_reranker=False,
        enable_query_expansion=False,
        enable_hybrid_search=False,
    )
    chunk = _sample_chunk()
    section = _sample_section()

    async def fake_load_vgu_index(_kb_name):
        return [chunk], [section]

    async def fake_coarse_search(*args, **kwargs):
        return ["s1"]

    def fake_filter_chunks(*args, **kwargs):
        return [chunk]

    async def fake_semantic_search(*args, **kwargs):
        return [chunk]

    def fake_rerank_chunks(query, chunks, top_k, enable_reranker=None):
        return chunks[:top_k]

    class DummyRag:
        async def _ensure_lightrag_initialized(self):
            return None

        async def aquery(self, *args, **kwargs):
            raise RuntimeError("No LightRAG instance available")

    monkeypatch.setattr(pipeline, "_load_vgu_index", fake_load_vgu_index)
    monkeypatch.setattr(pipeline, "_coarse_search", fake_coarse_search)
    monkeypatch.setattr(pipeline, "_filter_chunks_by_sections", fake_filter_chunks)
    monkeypatch.setattr(pipeline, "_semantic_search", fake_semantic_search)
    monkeypatch.setattr(pipeline, "_rerank_chunks", fake_rerank_chunks)
    monkeypatch.setattr(pipeline, "_get_rag_instance", lambda _kb_name: DummyRag())

    result = asyncio.run(
        pipeline.search(
            query="query",
            kb_name="kb",
            mode="hybrid",
            only_need_context=False,
            enable_reranker=False,
            enable_query_expansion=False,
            enable_hybrid_search=False,
            coarse_top_k=1,
            fine_top_k=1,
            final_top_k=1,
        )
    )

    assert result["provider"] == "vgu_course"
    assert result["metadata"]["answer_source"] == "retrieval_fallback"
    assert "sample content" in result["answer"]
