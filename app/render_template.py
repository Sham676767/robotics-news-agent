"""Validated, editable presentation settings; no legal content is generated here."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class RenderTemplate:
    font: str = "DejaVu Sans"
    background_top: str = "101C32"
    background_bottom: str = "244B61"
    text_color: str = "FFFFFF"
    accent_color: str = "7CE5CF"
    caption_size: int = 72
    words_per_caption: int = 5
    end_seconds: float = 3.0
    header_text: str = "ПРАВО РФ • ПРАКТИЧЕСКИЙ РАЗБОР"
    service_name: str = ""
    contact: str = ""

    def __post_init__(self) -> None:
        for name in ("background_top", "background_bottom", "text_color", "accent_color"):
            if not isinstance(getattr(self, name), str) or not re.fullmatch(r"[0-9A-Fa-f]{6}", getattr(self, name)):
                raise ValueError(f"Template {name} must be a six-digit RGB color")
        if type(self.caption_size) is not int or not 48 <= self.caption_size <= 88:
            raise ValueError("Template caption_size must be 48–88")
        if type(self.words_per_caption) is not int or not 1 <= self.words_per_caption <= 7:
            raise ValueError("Template words_per_caption must be 1–7")
        if type(self.end_seconds) not in (int, float) or not math.isfinite(self.end_seconds) or not 1 <= self.end_seconds <= 10:
            raise ValueError("Template end_seconds must be 1–10")
        for name, maximum in (("font", 80), ("header_text", 80), ("service_name", 80), ("contact", 120)):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
                raise ValueError(f"Template {name} must be a single line of at most {maximum} characters")
        if not re.fullmatch(r"[\w -]+", self.font):
            raise ValueError("Template font must be a font family name")


def load_render_template(path: Path) -> RenderTemplate:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError("Invalid render template YAML") from exc
    allowed = {item.name for item in fields(RenderTemplate)}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Render template must be a mapping with known fields")
    return RenderTemplate(**data)
