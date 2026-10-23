"""Provider selection is isolated from audio generation and artifact storage."""
from __future__ import annotations

from collections.abc import Callable

from app.config import Settings
from app.elevenlabs_tts import ElevenLabsTTSProvider
from app.tts import TTSProvider

_PROVIDERS: dict[str, Callable[[Settings], TTSProvider]] = {"elevenlabs": ElevenLabsTTSProvider}


def create_tts_provider(settings: Settings) -> TTSProvider:
    name = settings.tts_provider.strip().lower()
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise ValueError("Unsupported TTS_PROVIDER")
    return factory(settings)
