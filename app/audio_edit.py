"""Conservative PCM silence edits with an explicit mapping back to source word times."""
from __future__ import annotations

import array
import hashlib
import math
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from app.render_inputs import RenderAudio
from app.tts import WordTiming, validate_word_timings


@dataclass(frozen=True, slots=True)
class AudioEdit:
    audio: RenderAudio
    cuts: tuple[tuple[float, float], ...]
    speed: float
    tail_silence: float


def _samples(path: Path) -> tuple[array.array, int, int]:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2 or source.getcomptype() != "NONE":
            raise ValueError("Audio editing requires 16-bit PCM")
        rate, channels = source.getframerate(), source.getnchannels()
        samples = array.array("h", source.readframes(source.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples, rate, channels


def silence_ranges(path: Path, *, threshold_db: float = -45, window: float = .01) -> tuple[tuple[float, float], ...]:
    """RMS windows, not instantaneous zero crossings. Used on narration, never on music."""
    samples, rate, channels = _samples(path)
    step = max(1, round(rate * window)) * channels
    limit = 32768 * 10 ** (threshold_db / 20)
    ranges, start = [], None
    total = len(samples) / channels / rate
    for index in range(0, len(samples), step):
        block = samples[index:index + step]
        quiet = math.sqrt(sum(value * value for value in block) / len(block)) < limit
        time = index / channels / rate
        if quiet and start is None:
            start = time
        if not quiet and start is not None:
            ranges.append((start, time))
            start = None
    if start is not None:
        ranges.append((start, total))
    return tuple(ranges)


def edit_silence(audio: RenderAudio, target: Path) -> AudioEdit:
    """Trim leading/trailing silence to .08/.15s and interior pauses to .28s.

    Only measured quiet windows can be removed. Provider word intervals are retained;
    an interval spanning a long silent pause is remapped rather than dropped. The
    original WAV and timings stay untouched for audit and approval binding.
    """
    ranges = silence_ranges(audio.path)
    if len(ranges) == 1 and ranges[0][0] == 0 and ranges[0][1] >= audio.duration - .01:
        raise ValueError("Narration is entirely silent")
    cuts = []
    for start, end in ranges:
        if start <= .001:
            end_cut = max(start, end - .08)
            begin_cut = start
        elif end >= audio.duration - .01:
            begin_cut, end_cut = min(end, start + .15), end
        else:
            begin_cut, end_cut = start + .14, end - .14
        if end_cut - begin_cut > .01:
            cuts.append((begin_cut, end_cut))

    def remap(time: float) -> float:
        return time - sum(max(0, min(time, end) - start) for start, end in cuts if time > start)

    samples, rate, channels = _samples(audio.path)
    kept = array.array("h")
    cursor = 0
    quantized = []
    for start, end in cuts:
        first, last = round(start * rate), round(end * rate)
        kept.extend(samples[cursor * channels:first * channels])
        cursor = last
        quantized.append((first / rate, last / rate))
    kept.extend(samples[cursor * channels:])
    cuts = quantized
    duration = len(kept) / channels / rate
    words = tuple(WordTiming(word.word, remap(word.start), remap(word.end)) for word in audio.words)
    if sys.byteorder != "little":
        kept.byteswap()
    with wave.open(str(target), "wb") as output:
        output.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(kept.tobytes())
    validate_word_timings(" ".join(w.word for w in audio.words), words, duration)
    edited = RenderAudio(target, hashlib.sha256(target.read_bytes()).hexdigest(), duration, words, audio.timing_source)
    quiet = silence_ranges(target)
    tail = quiet[-1][1] - quiet[-1][0] if quiet and quiet[-1][1] >= duration - .01 else 0
    return AudioEdit(edited, tuple(cuts), 1.0, tail)
