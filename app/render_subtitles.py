"""Animated ASS overlays. Public links live in the caption, never in the video."""
from __future__ import annotations

import textwrap

from app.typography import layout
from app.reel_script import ReelScript
from app.render_inputs import RenderAudio
from app.render_template import RenderTemplate
from app.render_timeline import Overlay, overlays_for


def escape_ass(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\r", " ").replace("\n", " ")


def wrapped(text: str, width: int) -> str:
    return r"\N".join(textwrap.wrap(escape_ass(text), width=width, break_long_words=False, break_on_hyphens=False))


def stamp(seconds: float) -> str:
    value = max(0, round(seconds * 100))
    return f"{value // 360000}:{value // 6000 % 60:02}:{value // 100 % 60:02}.{value % 100:02}"


def color(rgb: str) -> str:
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}"


def ass_header(theme: RenderTemplate) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""
    for name, size, rgb in (("Caption", theme.caption_size, theme.text_color), ("Hook", 86, theme.text_color),
                            ("Header", 34, theme.text_color), ("Expert", 30, theme.accent_color),
                            ("Norm", 34, theme.text_color), ("CTA", 44, theme.text_color),
                            ("Disclaimer", 30, theme.text_color), ("Format", 32, theme.accent_color), ("Number", 104, theme.accent_color)):
        header += (f"Style: {name},{theme.font},{size},{color(rgb)},&H00000000,&H10101828,&H10101828,"
                   "-1,0,0,0,100,100,0,0,3,18,0,5,100,180,0,1\n")
    return header + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"


def render_overlay(item: Overlay, theme: RenderTemplate) -> str:
    kind = item.kind
    styles = {"hook": "Hook", "header": "Header", "expert": "Expert", "caption": "Caption", "norm": "Norm", "cta": "CTA", "disclaimer": "Disclaimer", "format": "Format", "number": "Number"}
    x1, y1, x2, y2 = item.bounds
    x, y = (x1 + x2) // 2, (y1 + y2) // 2
    # A hard clip is a final guard against any font substitution entering UI zones.
    tags = rf"{{\an5\pos({x},{y})\clip({x1},{y1},{x2},{y2})\fad(80,60)}}"
    if kind == "caption":
        size, lines = layout(item.text, theme.font, theme.caption_size, 60, x2-x1, y2-y1, max_lines=2)
        tags += rf"{{\fs{size}}}"
        text = r"\N".join(escape_ass(line) for line in lines)
        # Emphasize a number/sum or the last content word, using only source text.
        accent = next((w for w in item.text.split() if any(c.isdigit() for c in w)), item.text.split()[-1])
        marked = escape_ass(accent)
        emphasis = rf"{{\1c{color(theme.accent_color)}\fscx108\fscy108\t(0,160,\fscx100\fscy100)}}{marked}{{\1c{color(theme.text_color)}\fs{size}\fscx100\fscy100}}"
        text = text.replace(marked, emphasis, 1)
    else:
        initial = {"hook": 86, "header": 34, "expert": 30, "cta": 44, "disclaimer": 30, "norm": 34, "format": 32, "number": 104}[kind]
        minimum = 60 if kind in {"hook", "number"} else (26 if kind in {"cta", "norm"} else 24)
        size, lines = layout(item.text, theme.font, initial, minimum, x2-x1, y2-y1)
        text = r"\N".join(escape_ass(line) for line in lines)
        tags += rf"{{\fs{size}}}"
        if kind == "hook":
            tags = rf"{{\an5\move({x},{y + 28},{x},{y},0,220)\clip({x1},{y1},{x2},{y2})\fs{size}\fscx108\fscy108\t(0,240,\fscx100\fscy100)\fad(40,90)}}"
        elif kind == "cta":
            tags += rf"{{\1c{color(theme.accent_color)}}}"
    return f"Dialogue: 2,{stamp(item.start)},{stamp(item.end)},{styles[kind]},,0,0,0,,{tags}{text}\n"


def build_subtitles(script: ReelScript, audio: RenderAudio, theme: RenderTemplate, cta: str,
                    *, expert: str = "", overlays: tuple[Overlay, ...] | None = None) -> str:
    items = overlays or overlays_for(script, audio, header=theme.header_text, expert=expert or theme.service_name, cta=cta, font=theme.font)
    return ass_header(theme) + "".join(render_overlay(item, theme) for item in items)
