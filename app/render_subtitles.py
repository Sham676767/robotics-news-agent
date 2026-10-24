"""ASS presentation: timed spoken captions, evidence cards and end screen."""
from __future__ import annotations

import textwrap

from app.reel_script import ReelScript
from app.render_inputs import RenderAudio
from app.render_template import RenderTemplate


def escape_ass(text: str) -> str:
    # Prevent ASS tags, line breaks and drawing commands from user/source text.
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\r", " ").replace("\n", " ")


def wrapped(text: str, width: int) -> str:
    return r"\N".join(textwrap.wrap(escape_ass(text), width=width, break_long_words=True,
                                  break_on_hyphens=False))


def stamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    return f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02}:{centiseconds // 100 % 60:02}.{centiseconds % 100:02}"


def color(rgb: str) -> str:
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}"


def build_subtitles(script: ReelScript, audio: RenderAudio, theme: RenderTemplate, cta: str) -> str:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""
    def style(name: str, size: int, rgb: str, alignment: int, margin: int, box: bool = False) -> str:
        return (f"Style: {name},{theme.font},{size},{color(rgb)},&H00000000,&H80101828,&H80101828,"
                f"-1,0,0,0,100,100,0,0,{3 if box else 1},{14 if box else 3},0,{alignment},90,150,{margin},1\n")
    header += style("Caption", theme.caption_size, theme.text_color, 5, 0, True)
    header += style("Label", 32, theme.accent_color, 8, 240)
    header += style("Norm", 32, theme.text_color, 2, 360, True)
    header += style("Disclaimer", 28, theme.text_color, 2, 240)
    header += style("End", 58, theme.text_color, 5, 0, True)
    header += "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    events: list[str] = []
    def event(start: float, end: float, style_name: str, text: str) -> None:
        if round(end * 100) <= round(start * 100):
            return
        events.append(f"Dialogue: 0,{stamp(start)},{stamp(end)},{style_name},,0,0,0,,{text}\n")
    duration = audio.duration + theme.end_seconds
    event(0, audio.duration, "Label", wrapped(theme.header_text, 40))
    # All audible words are shown, including the hook and CTA, exactly once.
    group = []
    for index, word in enumerate(audio.words):
        if len(word.word) > 42:
            raise ValueError("A spoken word is too long for readable captions")
        if group and len(" ".join(item.word for item in group) + " " + word.word) > 42:
            event(group[0].start, group[-1].end, "Caption", wrapped(" ".join(item.word for item in group), 21))
            group = []
        group.append(word)
        if len(group) >= theme.words_per_caption or word.word.endswith((".", "?", "!", ";", ":")) or index == len(audio.words) - 1:
            event(group[0].start, group[-1].end, "Caption", wrapped(" ".join(item.word for item in group), 21))
            group = []
    norms = [source for source in script.sources if source.law and source.article]
    segment = audio.duration / len(norms)
    for index, source in enumerate(norms):
        norm = f"{source.law}, ст. {source.article}" + (f", ч. {source.part}" if source.part else "")
        # Use the original, complete URL; no invented short links or legal wording.
        event(index * segment, (index + 1) * segment, "Norm", wrapped(norm, 42) + r"\N" + wrapped(source.url, 48))
    event(0, duration, "Disclaimer", wrapped(script.disclaimer, 44))
    end = [wrapped(value, 25) for value in (theme.service_name, theme.contact, cta) if value]
    event(audio.duration, duration, "End", r"\N\N".join(end))
    return header + "".join(events)
