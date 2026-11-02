"""Validated, editable presentation settings; no legal content is generated here."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class RenderTemplate:
    style: str = "engaging"
    font: str = "DejaVu Sans"
    background_top: str = "DCE3E2"
    background_bottom: str = "EAE7E0"
    text_color: str = "FFFFFF"
    accent_color: str = "7CE5CF"
    caption_size: int = 72
    words_per_caption: int = 5
    cta_seconds: float = 5.5
    cta_background: str = "EAE7E0"
    cta_color: str = "162B3B"
    cta_accent: str = "285F55"
    end_seconds: float = 3.0
    header_text: str = "БИЗНЕС · ПРАВО РФ"
    service_name: str = ""
    contact: str = ""

    def __post_init__(self) -> None:
        if self.style not in {"engaging", "cinematic_still"}:
            raise ValueError("Unknown render style")
        for name in ("background_top", "background_bottom", "text_color", "accent_color", "cta_background", "cta_color", "cta_accent"):
            if not isinstance(getattr(self, name), str) or not re.fullmatch(r"[0-9A-Fa-f]{6}", getattr(self, name)):
                raise ValueError(f"Template {name} must be a six-digit RGB color")
        if type(self.caption_size) is not int or not 60 <= self.caption_size <= 88:
            raise ValueError("Template caption_size must be 60–88")
        if type(self.words_per_caption) is not int or not 2 <= self.words_per_caption <= 5:
            raise ValueError("Template words_per_caption must be 2–5")
        if type(self.end_seconds) not in (int, float) or not math.isfinite(self.end_seconds) or not 1 <= self.end_seconds <= 10:
            raise ValueError("Template end_seconds must be 1–10")
        if type(self.cta_seconds) not in (int, float) or not math.isfinite(self.cta_seconds) or not 5 <= self.cta_seconds <= 6:
            raise ValueError("Template cta_seconds must be 5–6")
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


def load_format_template(name: str) -> dict[str, object]:
    from app.editorial import FORMATS
    if name not in FORMATS:
        raise ValueError("Unknown editorial format template")
    path = Path(__file__).resolve().parents[1] / "templates/formats" / f"{name}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise ValueError("Invalid mini-template YAML") from None
    if (not isinstance(data, dict) or set(data) != {"badge", "steps"} or not isinstance(data["badge"], str)
            or not isinstance(data["steps"], list) or len(data["steps"]) != 3
            or any(not isinstance(text, str) or not text.strip() or len(text) > 40 or any(ord(c) < 32 for c in text)
                   for text in [data["badge"], *data["steps"]])):
        raise ValueError("Mini-template requires a short badge and exactly three step labels")
    return data
