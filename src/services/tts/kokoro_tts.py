# -*- coding: utf-8 -*-
"""
Kokoro TTS Adapter
==================

Local text-to-speech using Kokoro-82M model on GPU.
~558MB VRAM, 15x faster than real-time on P100.

Voices (lang_code='a' = American English):
    Female: af_heart, af_alloy, af_bella, af_nicole, af_sarah, af_sky
    Male:   am_adam, am_michael, am_echo, am_onyx

British English (lang_code='b'):
    Female: bf_emma, bf_isabella
    Male:   bm_george, bm_lewis

Usage:
    from src.services.tts.kokoro_tts import KokoroTTS

    tts = KokoroTTS.get_instance()
    audio_path = tts.generate("Hello world!", voice="af_heart", output_path="/tmp/hello.mp3")
"""

import io
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Singleton lock
_lock = threading.Lock()
_instance: Optional["KokoroTTS"] = None

# Voice name mapping: OpenAI-compatible → Kokoro native
# Allows seamless migration from OpenAI/Gemini TTS without changing voice names
VOICE_MAP = {
    # OpenAI standard voices → Kokoro equivalents
    "alloy": "af_alloy",
    "echo": "am_echo",
    "onyx": "am_onyx",
    "nova": "af_nicole",  # No nova in Kokoro, use Nicole (similar warm tone)
    "shimmer": "af_sky",  # No shimmer in Kokoro, use Sky (similar bright tone)
    "fable": "am_adam",  # No fable in Kokoro, use Adam (similar storytelling tone)
    # Google Gemini TTS voices → Kokoro equivalents
    "Zephyr": "af_heart",
    "Puck": "am_michael",
    "Charon": "am_onyx",
    "Kore": "af_bella",
    "Fenrir": "bm_george",
    "Aoede": "af_sarah",
    "Leda": "bf_emma",
    "Orus": "bm_lewis",
    "Perseus": "am_adam",
}

# Available Kokoro voices grouped by category
AVAILABLE_VOICES = {
    "american_female": ["af_heart", "af_alloy", "af_bella", "af_nicole", "af_sarah", "af_sky"],
    "american_male": ["am_adam", "am_michael", "am_echo", "am_onyx"],
    "british_female": ["bf_emma", "bf_isabella"],
    "british_male": ["bm_george", "bm_lewis"],
}

# Language code mapping
LANG_CODES = {
    "en": "a",  # American English (default)
    "en-us": "a",
    "en-gb": "b",  # British English
    "es": "es",  # Spanish
    "fr": "f",  # French
    "hi": "hi",  # Hindi
    "it": "it",  # Italian
    "ja": "j",  # Japanese
    "zh": "z",  # Chinese
    "pt": "p",  # Portuguese
}


class KokoroTTS:
    """
    Local TTS using Kokoro-82M model.

    Thread-safe singleton — pipeline is loaded once and reused.
    Generates audio at ~15x real-time speed on P100 GPU with ~558MB VRAM.
    """

    SAMPLE_RATE = 24000  # Kokoro native sample rate

    def __init__(self, lang_code: str = "a", device: Optional[str] = None):
        """
        Initialize Kokoro TTS pipeline.

        Args:
            lang_code: Language code ('a'=American, 'b'=British, etc.)
            device: 'cuda' or 'cpu'. Auto-detects if None.
        """
        import torch

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        self.device = device
        self.lang_code = lang_code
        self._pipeline = None
        self._voice_cache: dict = {}
        self._init_lock = threading.Lock()

        logger.info(f"KokoroTTS created: lang_code={lang_code}, device={device}")

    def _ensure_pipeline(self):
        """Lazy-load the pipeline on first use."""
        if self._pipeline is not None:
            return

        with self._init_lock:
            if self._pipeline is not None:
                return

            logger.info("Loading Kokoro-82M pipeline...")
            t0 = time.time()

            from kokoro import KPipeline

            self._pipeline = KPipeline(
                lang_code=self.lang_code,
                repo_id="hexgrad/Kokoro-82M",
                device=self.device,
            )

            elapsed = time.time() - t0
            logger.info(f"Kokoro-82M pipeline loaded in {elapsed:.1f}s on {self.device}")

            # Log VRAM usage
            if self.device == "cuda":
                import torch

                vram_mb = torch.cuda.memory_allocated() / 1024**2
                logger.info(f"Kokoro VRAM usage: {vram_mb:.0f}MB")

    def _resolve_voice(self, voice: str) -> str:
        """
        Resolve voice name to Kokoro-native voice ID.

        Supports:
        - Direct Kokoro voices: af_heart, am_adam, etc.
        - OpenAI voice names: alloy, echo, onyx, etc.
        - Google Gemini names: Zephyr, Puck, etc.
        """
        # Already a Kokoro voice name
        if voice.startswith(("af_", "am_", "bf_", "bm_")):
            return voice

        # Look up in mapping
        resolved = VOICE_MAP.get(voice)
        if resolved:
            logger.debug(f"Voice '{voice}' mapped to Kokoro voice '{resolved}'")
            return resolved

        # Unknown voice — fall back to af_heart
        logger.warning(f"Unknown voice '{voice}', falling back to 'af_heart'")
        return "af_heart"

    def _load_voice(self, voice_id: str):
        """Load and cache a voice tensor."""
        if voice_id in self._voice_cache:
            return self._voice_cache[voice_id]

        self._ensure_pipeline()

        try:
            voice_tensor = self._pipeline.load_voice(voice_id)
            self._voice_cache[voice_id] = voice_tensor
            logger.debug(f"Voice '{voice_id}' loaded and cached")
            return voice_tensor
        except Exception as e:
            logger.error(f"Failed to load voice '{voice_id}': {e}")
            # Try fallback
            if voice_id != "af_heart":
                logger.info("Falling back to 'af_heart'")
                return self._load_voice("af_heart")
            raise

    def generate(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        output_path: Optional[str] = None,
        output_format: str = "mp3",
    ) -> str:
        """
        Generate speech audio from text.

        Args:
            text: Input text to synthesize.
            voice: Voice name (Kokoro, OpenAI, or Gemini voice names supported).
            speed: Speech speed multiplier (0.5-2.0).
            output_path: Path to save audio file. If None, generates a temp path.
            output_format: Output format ('mp3' or 'wav'). Default 'mp3'.

        Returns:
            str: Path to the generated audio file.
        """
        import torch
        import soundfile as sf

        self._ensure_pipeline()

        # Resolve voice name
        voice_id = self._resolve_voice(voice)

        # Pre-load voice
        self._load_voice(voice_id)

        # Determine output path
        if output_path is None:
            import tempfile

            output_path = tempfile.mktemp(suffix=f".{output_format}")

        output_path = str(output_path)

        logger.info(
            f"Generating TTS: voice={voice_id}, speed={speed}, "
            f"text_len={len(text)}, format={output_format}"
        )

        t0 = time.time()

        # Generate audio chunks
        audio_chunks = []
        for gs, ps, audio in self._pipeline(text, voice=voice_id, speed=speed):
            audio_chunks.append(audio.cpu())

        if not audio_chunks:
            raise RuntimeError("Kokoro generated no audio output")

        # Concatenate all chunks
        full_audio = torch.cat(audio_chunks).numpy()
        duration = len(full_audio) / self.SAMPLE_RATE
        gen_time = time.time() - t0

        logger.info(
            f"TTS generated: {duration:.1f}s audio in {gen_time:.2f}s "
            f"(RTF={gen_time/duration:.3f}x)"
        )

        # Save audio
        if output_format == "mp3":
            self._save_as_mp3(full_audio, output_path)
        else:
            sf.write(output_path, full_audio, self.SAMPLE_RATE)

        logger.info(f"Audio saved to: {output_path}")
        return output_path

    def _save_as_mp3(self, audio_data, output_path: str):
        """Save audio data as MP3 using pydub or ffmpeg fallback."""
        import numpy as np

        try:
            # Try pydub first
            from pydub import AudioSegment

            # Convert float32 [-1, 1] to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)

            segment = AudioSegment(
                data=audio_int16.tobytes(),
                sample_width=2,  # 16-bit
                frame_rate=self.SAMPLE_RATE,
                channels=1,
            )
            segment.export(output_path, format="mp3", bitrate="192k")

        except ImportError:
            # Fallback: save as WAV, then convert with ffmpeg
            import subprocess
            import tempfile

            import soundfile as sf

            wav_path = tempfile.mktemp(suffix=".wav")
            try:
                sf.write(wav_path, audio_data, self.SAMPLE_RATE)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", wav_path, "-b:a", "192k", output_path],
                    capture_output=True,
                    check=True,
                )
            finally:
                if os.path.exists(wav_path):
                    os.remove(wav_path)

    @classmethod
    def get_instance(
        cls, lang_code: str = "a", device: Optional[str] = None
    ) -> "KokoroTTS":
        """
        Get or create singleton instance.

        Args:
            lang_code: Language code.
            device: 'cuda' or 'cpu'.

        Returns:
            KokoroTTS singleton instance.
        """
        global _instance

        if _instance is not None:
            return _instance

        with _lock:
            if _instance is not None:
                return _instance

            _instance = cls(lang_code=lang_code, device=device)
            return _instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)."""
        global _instance
        with _lock:
            _instance = None

    @staticmethod
    def list_voices() -> dict:
        """Return available voices grouped by category."""
        return AVAILABLE_VOICES.copy()


__all__ = ["KokoroTTS", "VOICE_MAP", "AVAILABLE_VOICES"]
