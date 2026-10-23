"""ElevenLabs adapter: native character alignment -> words; PCM -> standard WAV."""
from __future__ import annotations

import base64
import io
import logging
import math
import re
import time
import unicodedata
import wave
from typing import Any

import httpx

from app.config import Settings
from app.tts import SynthesizedSpeech, TTSError, WordTiming, validate_word_timings, wav_duration, word_spans

logger = logging.getLogger(__name__)
API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
SAMPLE_RATE = 24000
_TRANSIENT = {408, 409, 429, 500, 502, 503, 504}


def _retry_delay(config: Settings, attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        try:
            seconds = float(response.headers.get("Retry-After", ""))
            if math.isfinite(seconds):
                return max(0.0, min(seconds, config.tts_retry_max_seconds))
        except ValueError:
            pass
    delay = config.tts_retry_base_seconds
    for _ in range(attempt):
        delay = min(config.tts_retry_max_seconds, delay * 2)
        if delay >= config.tts_retry_max_seconds:
            break
    return delay


def _pcm_to_wav(pcm: bytes) -> bytes:
    if not pcm or len(pcm) % 2 or pcm.startswith((b"RIFF", b"ID3", b"OggS")):
        raise ValueError("Expected raw PCM16")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SAMPLE_RATE)
        file.writeframes(pcm)
    return buffer.getvalue()


def _alignment_words(raw: Any, text: str, duration: float) -> tuple[WordTiming, ...] | None:
    if not isinstance(raw, dict):
        raise ValueError("Expected alignment object")
    chars, starts, ends = (raw.get(key) for key in (
        "characters", "character_start_times_seconds", "character_end_times_seconds"))
    if any(not isinstance(value, list) for value in (chars, starts, ends)):
        raise ValueError("Missing character alignment arrays")
    if len(chars) != len(starts) or len(chars) != len(ends):
        raise ValueError("Alignment array lengths differ")
    if any(not isinstance(char, str) or len(char) != 1 for char in chars):
        raise ValueError("Invalid alignment character")
    previous_start = previous_end = 0.0
    for start, end in zip(starts, ends):
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in (start, end)):
            raise ValueError("Invalid character time")
        if (start < 0 or end < start or start < previous_start or end < previous_end
                or end > duration + 0.02):
            raise ValueError("Invalid character time order or duration")
        previous_start, previous_end = start, end
    aligned = "".join(chars)
    source_words, aligned_words = word_spans(text), word_spans(aligned)
    normalized = lambda value: unicodedata.normalize("NFC", value)
    if [normalized(word.group()) for word in source_words] != [normalized(word.group()) for word in aligned_words]:
        return None
    result = tuple(WordTiming(original.group(), min(duration, starts[span.start()]),
                              min(duration, ends[span.end() - 1]))
                   for original, span in zip(source_words, aligned_words))
    validate_word_timings(text, result, duration)
    return result


class ElevenLabsTTSProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.elevenlabs_api_key:
            raise TTSError("ELEVENLABS_API_KEY is not configured")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", settings.elevenlabs_voice_id):
            raise TTSError("ELEVENLABS_VOICE_ID must be configured as a valid voice identifier")
        self._settings = settings

    def synthesize(self, text: str) -> SynthesizedSpeech:
        if not isinstance(text, str) or not word_spans(text):
            raise ValueError("TTS requires non-empty spoken text")
        config = self._settings
        for attempt in range(config.tts_max_attempts):
            response: httpx.Response | None = None
            reason = "transport_error"
            try:
                response = httpx.post(
                    f"{API_URL}/{config.elevenlabs_voice_id}/with-timestamps",
                    headers={"xi-api-key": config.elevenlabs_api_key, "Content-Type": "application/json",
                             "Accept": "application/json"},
                    params={"output_format": "pcm_24000"},
                    json={"text": text, "model_id": config.elevenlabs_model_id},
                    timeout=config.tts_timeout,
                )
            except httpx.TransportError:
                pass
            else:
                if response.status_code == 200:
                    try:
                        return self._parse_response(response.json(), text)
                    except (ValueError, TypeError, TTSError):
                        # Do not repeat a paid successful generation because metadata is corrupt.
                        raise TTSError("ElevenLabs returned invalid audio or character timings") from None
                if response.status_code not in _TRANSIENT:
                    raise TTSError(f"ElevenLabs HTTP {response.status_code}; request rejected")
                reason = f"http_{response.status_code}"
            if attempt + 1 < config.tts_max_attempts:
                delay = _retry_delay(config, attempt, response)
                logger.warning("TTS %s; retry %d/%d in %.1fs", reason, attempt + 2, config.tts_max_attempts, delay)
                time.sleep(delay)
        raise TTSError(f"ElevenLabs request failed after {config.tts_max_attempts} attempts")

    def _parse_response(self, data: Any, text: str) -> SynthesizedSpeech:
        if not isinstance(data, dict) or not isinstance(data.get("audio_base64"), str):
            raise ValueError("Missing base64 audio")
        audio = _pcm_to_wav(base64.b64decode(data["audio_base64"], validate=True))
        duration = wav_duration(audio)
        timings: tuple[WordTiming, ...] | None = None
        note = "no_alignment"
        for key in ("alignment", "normalized_alignment"):
            raw = data.get(key)
            if raw is not None:
                candidate = _alignment_words(raw, text, duration)
                if candidate is not None:
                    timings, note = candidate, key
                    break
                note = "alignment_text_mismatch"
        logger.info("ElevenLabs audio received; native word timings: %s", timings is not None)
        return SynthesizedSpeech(audio, "elevenlabs", self._settings.elevenlabs_model_id,
                                 self._settings.elevenlabs_voice_id, timings, note)
