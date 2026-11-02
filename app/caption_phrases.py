"""Phrase boundaries chosen from word timings, punctuation and Russian function words."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from collections.abc import Callable

from app.tts import WordTiming

FUNCTION_WORDS = frozenset("а и но или либо да зато однако что чтобы как если когда пока хотя ведь ли же бы не ни в во на о об обо от до за из изо к ко с со у по под при про над перед без для через между из-за из-под около после ради благодаря ввиду вследствие согласно вопреки несмотря".split())


PARTICLES = frozenset("ли бы же то не ни".split())


def starts_particle(text: str) -> bool:
    words = text.split()
    return bool(words and words[0].strip(".,:;!?…\"'«»()[]—–").casefold() in PARTICLES)


def dangling_line(text: str) -> bool:
    # A particle stays with its previous word, including at a line boundary.
    return dangling(text) and text.split()[-1].strip(".,:;!?…«»").casefold() not in PARTICLES


def display_text(text: str) -> str:
    return text.rstrip(" ,;:—–-")


def dangling(text: str) -> bool:
    words = text.split()
    return bool(words and words[-1].strip(".,:;!?…\"'«»()[]—–").casefold() in FUNCTION_WORDS)


@dataclass(frozen=True, slots=True)
class CaptionPhrase:
    words: tuple[WordTiming, ...]

    @property
    def text(self) -> str:
        return display_text(" ".join(item.word for item in self.words))

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def phrase_captions(words: tuple[WordTiming, ...], maximum: int = 5, *, fits: Callable[[str], bool] | None = None) -> tuple[CaptionPhrase, ...]:
    """Globally partition into 2–5 words; punctuation/pauses favor meaningful boundaries.

    Fail closed for impossible input (e.g. an orphan preposition at the end), rather
    than silently emitting a broken caption or losing an audible word.
    """
    if not 2 <= maximum <= 5 or not words:
        raise ValueError("Captions require words and a maximum of 2–5")

    @lru_cache(None)
    def best(start: int) -> tuple[float, tuple[int, ...]] | None:
        if start == len(words):
            return 0.0, ()
        options = []
        for count in range(2, maximum + 1):
            end = start + count
            if end > len(words) or starts_particle(words[start].word) or dangling(words[end - 1].word):
                continue
            # Keep the text compact before checking its measured font layout.
            text = display_text(" ".join(word.word for word in words[start:end]))
            if len(text) > 46 or any(len(word.word) > 22 for word in words[start:end]):
                continue
            try:
                caption_lines(text)
            except ValueError:
                continue
            if fits is not None and not fits(text):
                continue
            rest = best(end)
            if rest is None:
                continue
            punctuation = words[end - 1].word.endswith((".", "!", "?", ";", ":", ","))
            gap = words[end].start - words[end - 1].end if end < len(words) else 0
            # Penalize crossing strong punctuation inside a screen.
            crossed = sum(word.word.endswith((".", "!", "?", ";", ":", ",")) for word in words[start:end - 1])
            score = rest[0] + abs(count - 3) * .35 + crossed * 3 - (1.5 if punctuation else 0) - min(gap, .3) * 2
            options.append((score, (end,) + rest[1]))
        return min(options, key=lambda item: item[0]) if options else None

    solution = best(0)
    if solution is None:
        raise ValueError("Speech cannot be split into readable 2–5-word captions without dangling function words")
    result, start = [], 0
    for end in solution[1]:
        result.append(CaptionPhrase(words[start:end]))
        start = end
    return tuple(result)


def caption_lines(text: str, width: int = 23) -> tuple[str, ...]:
    """At most two lines; line breaks also keep a preposition with its noun."""
    if len(text) <= width:
        return (text,)
    words = text.split()
    splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))
              if not dangling_line(words[i - 1]) and not starts_particle(words[i])]
    splits = [pair for pair in splits if max(map(len, pair)) <= width]
    if not splits:
        raise ValueError("Caption phrase is too wide for the safe area")
    return min(splits, key=lambda pair: abs(len(pair[0]) - len(pair[1])))
