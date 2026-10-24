"""Bind local audio and validated word timings to the reviewed script."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.reel_script import ReelScript
from app.script_review import digest
from app.tts import WordTiming, validate_word_timings, wav_duration


@dataclass(frozen=True, slots=True)
class RenderAudio:
    path: Path
    sha256: str
    duration: float
    words: tuple[WordTiming, ...]
    timing_source: str


def load_render_audio(path: Path, script: ReelScript) -> RenderAudio:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported TTS metadata schema")
    if data.get("script_sha256") != digest(script.to_dict()) or data.get("text") != script.voiceover:
        raise ValueError("TTS metadata does not match the reviewed script")
    if data.get("text_sha256") != hashlib.sha256(script.voiceover.encode()).hexdigest():
        raise ValueError("TTS text checksum mismatch")
    name = data.get("audio_file")
    if not isinstance(name, str) or name != "audio.wav":
        raise ValueError("TTS audio_file must be the paired local audio.wav")
    audio = path.parent / name
    if audio.is_symlink():
        raise ValueError("Paired audio must not be a symbolic link")
    raw = audio.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum != data.get("audio_sha256"):
        raise ValueError("Audio checksum mismatch")
    duration = wav_duration(raw)
    declared = data.get("duration_seconds")
    if type(declared) not in (int, float) or not math.isfinite(declared) or abs(declared - duration) > 1e-6:
        raise ValueError("TTS duration does not match WAV")
    if data.get("timing_source") not in ("provider", "estimated"):
        raise ValueError("Unknown timing_source")
    try:
        words = tuple(WordTiming(**item) for item in data["word_timings"])
    except (KeyError, TypeError) as exc:
        raise ValueError("Invalid word timing records") from exc
    validate_word_timings(script.voiceover, words, duration)
    return RenderAudio(audio.resolve(), checksum, duration, words, data["timing_source"])
