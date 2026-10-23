"""Provider-neutral synthesis, timing validation and paired artifact persistence."""
from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.tts import TTSProvider, TTSError, WordTiming, estimate_word_timings, validate_word_timings, wav_duration, word_spans
from app.tts_factory import create_tts_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TTSResult:
    audio_path: Path
    timings_path: Path
    duration_seconds: float
    word_timings: tuple[WordTiming, ...]
    timing_source: str
    provider: str

    def to_dict(self) -> dict[str, str | float | int]:
        return {"audio_path": str(self.audio_path), "timings_path": str(self.timings_path),
                "duration_seconds": self.duration_seconds, "word_count": len(self.word_timings),
                "timing_source": self.timing_source, "provider": self.provider}


def synthesize_audio(text: str, settings: Settings, *, provider: TTSProvider | None = None,
                     script_sha256: str | None = None) -> TTSResult:
    if not isinstance(text, str) or not word_spans(text):
        raise ValueError("TTS requires non-empty spoken text")
    output_dir = settings.tts_output_dir
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("TTS_OUTPUT_DIR must be a directory")
    adapter = provider if provider is not None else create_tts_provider(settings)
    speech = adapter.synthesize(text)
    duration = wav_duration(speech.audio_wav)
    if any(not isinstance(value, str) or not value.strip()
           for value in (speech.provider, speech.model, speech.voice_id)):
        raise TTSError("Provider returned incomplete synthesis metadata")
    native = speech.word_timings is not None
    timings = (estimate_word_timings(text, duration) if speech.word_timings is None else speech.word_timings)
    validate_word_timings(text, timings, duration)
    source = "provider" if native else "estimated"
    if not native:
        logger.warning("TTS word timings estimated from phrase lengths; exact alignment unavailable")
    metadata = {
        "schema_version": 1, "provider": speech.provider, "model": speech.model, "voice_id": speech.voice_id,
        "audio_file": "audio.wav", "audio_sha256": hashlib.sha256(speech.audio_wav).hexdigest(),
        "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "script_sha256": script_sha256,
        "duration_seconds": duration, "timing_source": source,
        "timing_method": "provider_word_alignment" if native else "phrase_length_v1",
        "timing_note": speech.timing_note or ("" if native else "provider_did_not_return_word_timings"),
        "word_timings": [asdict(item) for item in timings],
        "publication_allowed": False, "human_review_required": True,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / f"tts-{uuid4().hex}"
    # Both files become visible together; previous generations are never overwritten.
    with tempfile.TemporaryDirectory(prefix=".tts-", dir=output_dir) as temporary:
        staging = Path(temporary)
        (staging / "audio.wav").write_bytes(speech.audio_wav)
        (staging / "timings.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2,
                                                       allow_nan=False) + "\n", encoding="utf-8")
        if final.exists() or final.is_symlink():
            raise FileExistsError("TTS result directory already exists")
        staging.rename(final)
    logger.info("TTS audio and %s word timings saved: %s", source, final)
    return TTSResult(final / "audio.wav", final / "timings.json", duration, timings, source, speech.provider)
