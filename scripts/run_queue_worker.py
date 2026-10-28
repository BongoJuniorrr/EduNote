#!/usr/bin/env python3
import base64
import mimetypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from src.services.document_previews import run_document_preview
from src.services.llm import get_llm_config
from src.services.ocr import ensure_ocr_allowed, extract_basic, extract_heavy
from src.services.queue import QueueWorker
from src.services.rag.service import DEFAULT_KB_BASE_DIR
from src.services.storage import get_storage_service
from src.services.tts.kokoro_tts import KokoroTTS
from src.tools.rag_tool import rag_search


def run_tts(payload, job):
    text = str(payload.get("text", "")).strip()
    if not text or len(text) > 50_000:
        raise ValueError("TTS text must contain between 1 and 50000 characters")
    voice = str(payload.get("voice", "af_heart"))
    output = get_storage_service().user_root(job.owner_id) / "audio" / f"{job.id}.mp3"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        tts = KokoroTTS.get_instance(device=f"cuda:{payload.get('gpu_index', 0)}")
        tts.generate(text, voice=voice, output_path=str(output))
    finally:
        KokoroTTS.reset_instance()
    return {"audio_path": str(output), "voice": voice}


async def run_rag_query(payload, job):
    return await rag_search(
        query=str(payload["query"]),
        kb_name=str(payload["kb_name"]),
        mode=str(payload.get("mode", "hybrid")),
        provider=payload.get("provider"),
        kb_base_dir=DEFAULT_KB_BASE_DIR,
    )


def run_ocr_basic(payload, job):
    path = get_storage_service().safe_path(job.owner_id, str(payload["relative_path"]))
    return extract_basic(path)


def run_ocr_heavy(payload, job):
    path = get_storage_service().safe_path(job.owner_id, str(payload["relative_path"]))
    return extract_heavy(path, gpu_index=int(payload.get("gpu_index", 0)))


async def run_ocr_remote(payload, job):
    ensure_ocr_allowed("basic", remote=True)
    config = get_llm_config()
    path = get_storage_service().safe_path(job.owner_id, str(payload["relative_path"]))
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not mime.startswith("image/"):
        raise ValueError("Remote OCR accepts image files; use basic OCR for PDF/text")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    endpoint = config.base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={
                "model": config.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract all readable text from this image. Return only the text.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{encoded}"},
                            },
                        ],
                    }
                ],
                "temperature": 0,
            },
        )
        response.raise_for_status()
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"text": content[:100_000], "engine": "workspace-openai-compatible-ocr"}


def build_worker():
    worker = QueueWorker()
    worker.register("document_preview", run_document_preview, isolated=True)
    worker.register("tts", run_tts, requires_gpu=True, isolated=True)
    worker.register("rag_query_gpu", run_rag_query, requires_gpu=True, isolated=True)
    worker.register("rag_query_remote", run_rag_query, isolated=True)
    worker.register("ocr_basic", run_ocr_basic, isolated=True)
    worker.register("ocr_heavy", run_ocr_heavy, requires_gpu=True, isolated=True)
    worker.register("ocr_remote", run_ocr_remote, isolated=True)
    from src.services.learning.workflows import run_diagnostics, run_evidence, run_study_pack

    worker.register("evidence", run_evidence, isolated=True)
    worker.register("study_pack", run_study_pack, isolated=True)
    worker.register("settings_diagnostics", run_diagnostics, isolated=True)
    return worker


if __name__ == "__main__":
    build_worker().run_forever()
