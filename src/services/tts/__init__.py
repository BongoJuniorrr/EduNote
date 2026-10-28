# -*- coding: utf-8 -*-
"""
TTS Service
===========

Text-to-Speech configuration for EduNote.

Usage:
    from src.services.tts import get_tts_config

    config = get_tts_config()
    # config = {"model": "tts-1", "api_key": "...", "base_url": "...", "voice": "alloy"}
"""

from .config import get_tts_config

# KokoroTTS is only available when the kokoro package is installed.
# In the slim production build, kokoro is not installed and TTS_BINDING=openai is used.
# Guard the import so the rest of the application can load without kokoro.
try:
    from .kokoro_tts import KokoroTTS
    _KOKORO_AVAILABLE = True
except ImportError:
    KokoroTTS = None  # type: ignore[assignment,misc]
    _KOKORO_AVAILABLE = False

__all__ = ["get_tts_config", "KokoroTTS"]
