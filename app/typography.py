"""Measure the actual bundled font before drawing, instead of relying on character counts."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from app.caption_phrases import dangling

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
        lines, line = [], []
        for word in words:
            if line and font.getlength(" ".join((*line, word))) * 1.08 > width - 44:
                # Move a trailing function word to the next line, rather than splitting its phrase.
                carry = []
                while line and dangling(line[-1]):
                    carry.insert(0, line.pop())
                if line:
                    lines.append(" ".join(line))
                line = carry
            line.append(word)
        if line:
            lines.append(" ".join(line))
        if (len(lines) <= max_lines and (len(lines) * current * 1.22 + 40) * 1.08 <= height
                and all(font.getlength(line) * 1.08 <= width - 44 for line in lines)):
            return current, tuple(lines)
    raise ValueError("Overlay cannot fit safe bounds at the minimum readable font size")
