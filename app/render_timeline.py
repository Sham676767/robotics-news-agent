"""A reviewable timeline, including measured bounds for every meaningful overlay."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from app.caption_phrases import phrase_captions
from app.reel_script import ReelScript
from app.render_inputs import RenderAudio

SAFE = (90, 250, 930, 1520)


@dataclass(frozen=True, slots=True)
class Shot:
    start: float
    end: float
    asset: int
    motion: str


@dataclass(frozen=True, slots=True)
class Overlay:
    kind: str
    start: float
    end: float
    text: str
    bounds: tuple[int, int, int, int]

    def to_dict(self) -> dict:
        return asdict(self)


def shots_for(duration: float, assets: int) -> tuple[Shot, ...]:
    if not math.isfinite(duration) or duration <= 0 or assets < 1:
        raise ValueError("Invalid shot plan")
    count = math.ceil(duration / 3.5)
    # Frame-aligned boundaries, with the final fragment absorbed into equal-length shots.
    boundaries = [round(i * duration / count * 30) / 30 for i in range(count + 1)]
    return tuple(Shot(boundaries[i], boundaries[i + 1], i % assets, "push_in" if i % 2 == 0 else "pull_out") for i in range(count))


def cta_start(script: ReelScript, audio: RenderAudio) -> float:
    count = len(script.voiceover.strip().split("\n\n")[-1].split())
    return audio.words[-count].start


def norm_overlays(script: ReelScript, audio: RenderAudio) -> tuple[Overlay, ...]:
    result = []
    # Only a spoken, explicit reference triggers a card. No rotation through unspoken norms.
    for i, word in enumerate(audio.words):
        if not re.fullmatch(r"(?:ст\.?|статья|статье|статьи|статью)", word.word, re.I):
            continue
        following = audio.words[i + 1:i + 8]
        for source in script.sources:
            if source.law and source.article and following and following[0].word.strip(".,:;") == source.article:
                law = source.law
                number = re.search(r"\d+[\w.-]*-ФЗ", law, re.I)
                if number:
                    law = f"ФЗ № {number.group()}"
                text = f"ст. {source.article} {law}"
                if source.part:
                    text = f"ч. {source.part} " + text
                end = min(audio.duration, word.start + 3)
                result.append(Overlay("norm", word.start, end, text, (100, 1260, 900, 1380)))
    return tuple(result)


def overlays_for(script: ReelScript, audio: RenderAudio, *, header: str, expert: str, cta: str, font: str = "DejaVu Sans", maximum_words: int = 5) -> tuple[Overlay, ...]:
    overlays = [Overlay("header", 0, audio.duration, header, (100, 270, 900, 370)),
                Overlay("hook", 0, min(3, audio.duration), script.hook, (100, 580, 900, 1140))]
    if expert:
        overlays.append(Overlay("expert", 0, audio.duration, expert, (100, 390, 900, 470)))
    from app.typography import layout
    def fits(text: str) -> bool:
        try:
            layout(text, font, 60, 60, 800, 490, max_lines=3)
            return True
        except ValueError:
            return False
    for phrase in phrase_captions(audio.words, maximum=maximum_words, fits=fits):
        # Hook already has a large complete card, without a second overlapping caption.
        if phrase.end > 3:
            overlays.append(Overlay("caption", max(3, phrase.start), phrase.end, phrase.text, (100, 650, 900, 1140)))
    # Money, deadlines and article numbers use only tokens already spoken/reviewed.
    for index, word in enumerate(audio.words):
        if re.fullmatch(r"[₽№]?\d[\d.,–-]*(?:-ФЗ)?[.,:;!?]?", word.word, re.I):
            text = word.word.rstrip(".,:;!?")
            if index + 1 < len(audio.words) and audio.words[index + 1].word.rstrip(".,:;!?").casefold() in {"руб", "рубль", "рубля", "рублей", "₽", "%", "день", "дня", "дней", "дн", "час", "часа", "часов", "месяц", "месяца", "месяцев", "суток", "сутки"}:
                text += " " + audio.words[index + 1].word.rstrip(".,:;!?")
            overlays.append(Overlay("number", word.start, min(audio.duration, max(word.end, word.start + .8)), text, (100, 540, 900, 740)))
    overlays.extend(norm_overlays(script, audio))
    start = max(cta_start(script, audio), audio.duration - 8)
    overlays.append(Overlay("cta", start, audio.duration, cta, (100, 1160, 900, 1390)))
    overlays.append(Overlay("disclaimer", max(0, audio.duration - 1.6), audio.duration, script.disclaimer, (100, 1420, 900, 1500)))
    validate_overlays(tuple(overlays), audio.duration)
    return tuple(overlays)


def validate_overlays(overlays: tuple[Overlay, ...], duration: float) -> None:
    for item in overlays:
        x1, y1, x2, y2 = item.bounds
        if not (SAFE[0] <= x1 < x2 <= SAFE[2] and SAFE[1] <= y1 < y2 <= SAFE[3]
                and 0 <= item.start < item.end <= duration + .001):
            raise ValueError("Overlay exceeds safe area or video duration")
