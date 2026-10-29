"""Opaque configuration identity; raw endpoints and credentials never leave this module."""

from dataclasses import asdict
import hashlib
import json


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def model_fingerprint() -> str:
    from src.services.embedding import get_embedding_config
    from src.services.llm import get_llm_config

    value = {}
    for key, load in (("llm", get_llm_config), ("embedding", get_embedding_config)):
        try:
            value[key] = asdict(load())
        except Exception as error:
            # Diagnostics must still be usable before a model is configured.
            value[key] = {"configured": False, "error_type": type(error).__name__}
    return _digest(value)


def workflow_fingerprint() -> str:
    from src.services.document_processing import get_document_config

    return _digest({"models": model_fingerprint(), "document": get_document_config().model_dump()})
