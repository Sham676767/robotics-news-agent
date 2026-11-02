"""Measure the actual bundled font before drawing, instead of relying on character counts."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from app.caption_phrases import dangling_line, starts_particle

BUNDLED_FONT = Path(__file__).resolve().parents[1] / "assets/fonts/DejaVuSans-Bold.ttf"


@lru_cache(None)
def font_file(family: str) -> Path:
    if family == "DejaVu Sans":
        return BUNDLED_FONT
    try:
        match = subprocess.run(["fc-match", "-f", "%{family}\n%{file}", family + ":style=Bold"],
                               capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()
        if len(match) != 2 or family.casefold() not in match[0].casefold() or not Path(match[1]).is_file():
            raise ValueError
    except (ValueError, OSError, subprocess.SubprocessError):
        raise ValueError("Configured font is not installed") from None
    return Path(match[1])


@lru_cache(128)
def measured_font(family: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_file(family)), size)


def layout(text: str, family: str, size: int, minimum: int, width: int, height: int, *, max_lines: int = 5) -> tuple[int, tuple[str, ...]]:
    words = text.split()
    # Reserve the opaque panel padding and the maximum 8% entrance animation scale.
    for current in range(size, minimum - 1, -1):
        font = measured_font(family, current)
        @lru_cache(None)
        def split(start: int, remaining: int) -> tuple[str, ...] | None:
            if start == len(words):
                return ()
            if remaining == 0 or (start > 0 and starts_particle(words[start])):
                return None
            choices = []
            for end in range(start + 1, len(words) + 1):
                line = " ".join(words[start:end])
                if font.getlength(line) * 1.08 > width - 44:
                    break
                if end < len(words) and dangling_line(words[end-1]):
                    continue
                rest = split(end, remaining-1)
                if rest is not None:
                    choices.append((line,) + rest)
            return min(choices, key=lambda lines: (len(lines), max(map(len, lines))-min(map(len, lines)))) if choices else None
        allowed = min(max_lines, max(0, int((height / 1.08 - 40) / (current * 1.22))))
        lines = split(0, allowed)
        if lines:
            return current, lines
    raise ValueError("Overlay cannot fit safe bounds at the minimum readable font size")
