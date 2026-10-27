import asyncio
import json
import logging
import os
from pathlib import Path
import re
import threading

logger = logging.getLogger(__name__)


class IconFinderService:
    """Search bundled icons without making application startup depend on a model."""

    def __init__(self, icons_path: Path | None = None):
        self._icons_path = icons_path or Path(__file__).resolve().parents[1] / "assets/icons.json"
        self._icons = None
        self._lock = threading.RLock()
        self._collection = None

    def _load_icons(self):
        with self._lock:
            if self._icons is None:
                data = json.loads(self._icons_path.read_text(encoding="utf-8"))
                self._icons = [item for item in data["icons"] if item["name"].endswith("-bold")]
            return self._icons

    @staticmethod
    def _words(text):
        # The bundled metadata is English; light plural normalization helps titles.
        return {word.removesuffix("s") for word in re.findall(r"[a-z0-9]+", text.casefold())}

    def _keyword_search(self, query, k):
        words = self._words(query)
        ranked = []
        for icon in self._load_icons():
            tags = icon.get("tags", [])
            description = tags if isinstance(tags, str) else " ".join(map(str, tags))
            name_words = self._words(icon["name"].removesuffix("-bold"))
            score = 3 * len(words & name_words) + len(words & self._words(description))
            ranked.append((-score, icon["name"]))
        ranked.sort()
        return [f"/static/icons/bold/{name}.svg" for _, name in ranked[:k]]

    def _semantic_search(self, query, k):
        # Optional model dependencies and downloads are deferred until explicitly used.
        with self._lock:
            if self._collection is None:
                import chromadb
                from chromadb.config import Settings
                from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

                cache = Path(os.getenv("APP_DATA_DIRECTORY", "/app_data")) / "icon_search"
                cache.mkdir(parents=True, exist_ok=True)
                embedding = ONNXMiniLM_L6_V2()
                embedding.DOWNLOAD_PATH = str(cache / "models")
                embedding._download_model_if_not_exists()
                client = chromadb.PersistentClient(path=str(cache), settings=Settings(anonymized_telemetry=False))
                collection = client.get_or_create_collection(
                    "icons", embedding_function=embedding, metadata={"hnsw:space": "cosine"}
                )
                if not collection.count():
                    icons = self._load_icons()
                    collection.add(
                        documents=[f"{item['name']} {item.get('tags', [])}" for item in icons],
                        ids=[item["name"] for item in icons],
                    )
                self._collection = collection
        result = self._collection.query(query_texts=[query], n_results=k)
        allowed = {item["name"] for item in self._load_icons()}
        return [f"/static/icons/bold/{name}.svg" for name in result["ids"][0] if name in allowed]

    async def search_icons(self, query: str, k: int = 1):
        limit = max(1, min(int(k), 25))
        if os.getenv("PRESENTON_SEMANTIC_ICONS", "false").lower() in {"true", "1", "yes"}:
            try:
                result = await asyncio.to_thread(self._semantic_search, query, limit)
                if result:
                    return result
            except Exception:
                logger.warning("Semantic icon search unavailable; using bundled keyword search")
        return await asyncio.to_thread(self._keyword_search, query, limit)


ICON_FINDER_SERVICE = IconFinderService()
