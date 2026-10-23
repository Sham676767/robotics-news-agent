"""Provider-neutral speech contract. Every adapter returns PCM WAV audio."""
from __future__ import annotations

import io
import math
import re
import wave
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class TTSError(RuntimeError):
    """A sanitized provider or audio validation failure."""


@dataclass(frozen=True, slots=True)
class WordTiming:
    word: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class SynthesizedSpeech:
    audio_wav: bytes
    provider: str
    model: str
    voice_id: str
    word_timings: tuple[WordTiming, ...] | None = None
    timing_note: str = ""


@runtime_checkable
class TTSProvider(Protocol):
    def synthesize(self, text: str) -> SynthesizedSpeech:
        """Return audio and optional word times, without writing pipeline files."""
        ...


def word_spans(text: str) -> tuple[re.Match[str], ...]:
    # Preserve punctuation on caption words; standalone punctuation is not a word.
    return tuple(match for match in re.finditer(r"\S+", text) if any(char.isalnum() for char in match.group()))


def wav_duration(audio: bytes) -> float:
    try:
        if not isinstance(audio, bytes) or not audio:
            raise ValueError("Empty audio")
        with wave.open(io.BytesIO(audio), "rb") as file:
            if file.getcomptype() != "NONE" or file.getsampwidth() != 2:
                raise ValueError("Expected 16-bit PCM WAV")
            frames, rate, channels = file.getnframes(), file.getframerate(), file.getnchannels()
            if frames < 1 or rate < 1 or channels < 1:
                raise ValueError("Empty or invalid WAV")
            if len(file.readframes(frames)) != frames * channels * 2:
                raise ValueError("Truncated WAV")
            return frames / rate
    except (ValueError, EOFError, wave.Error, TypeError):
        raise TTSError("Invalid or truncated PCM WAV audio") from None


def validate_word_timings(text: str, timings: tuple[WordTiming, ...], duration: float) -> None:
    if not math.isfinite(duration) or duration <= 0:
        raise TTSError("Invalid audio duration")
    if not timings or [item.word for item in timings] != [match.group() for match in word_spans(text)]:
        raise TTSError("Word timings do not cover the requested text")
    previous = 0.0
    for item in timings:
        if any(type(value) not in {int, float} or not math.isfinite(value) for value in (item.start, item.end)):
            raise TTSError("Invalid word timestamp")
        if item.start < 0 or item.end <= item.start or item.start + 1e-8 < previous or item.end > duration + 1e-8:
            raise TTSError("Word timestamps overlap or exceed the audio duration")
        previous = item.end


def estimate_word_timings(text: str, duration: float) -> tuple[WordTiming, ...]:
    """Allocate actual audio duration by phrase lengths, with punctuation pauses."""
    spans = word_spans(text)
    if not spans or not math.isfinite(duration) or duration <= 0:
        raise TTSError("Cannot estimate timings for empty text or audio")
    weights: list[int] = []
    pauses: list[int] = []
    for index, span in enumerate(spans):
        weights.append(max(1, sum(char.isalnum() for char in span.group())))
        following = text[span.end():spans[index + 1].start()] if index + 1 < len(spans) else ""
        pause = 6 if span.group().endswith((".", "!", "?", "…")) else (3 if span.group().endswith((",", ";", ":")) else 0)
        if "\n" in following:
            pause = max(pause, 9)
        pauses.append(pause)
    unit = duration / (sum(weights) + sum(pauses))
    cursor = 0.0
    result: list[WordTiming] = []
    for span, weight, pause in zip(spans, weights, pauses):
        end = min(duration, cursor + weight * unit)
        result.append(WordTiming(span.group(), cursor, end))
        cursor = end + pause * unit
    timings = tuple(result)
    validate_word_timings(text, timings, duration)
    return timings
