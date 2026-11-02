"""Editorial choices are explicit, source-reviewed and travel with the script."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

FORMATS = ("question_answer", "three_mistakes", "before_after", "checklist")
DEFAULT_CTA = "Нужен разбор? Напишите «{keyword}» {contact}. Сохраните, чтобы не потерять."
# Advertising promises are disallowed even when preceded by a conditional clause.
_PROMISE = re.compile(r"\b(?:выиграем|верн[её]м|добь[её]мся|обеспечим)\b|гарант\w*|(?:точно|обязательно|всегда)\s+(?:выигра\w*|верн\w*|получ\w*)|выиграем\s+(?:дело|суд)|без\s+рисков", re.I)


def client_cta(template: str, keyword: str, contact: str) -> str:
    if not keyword.strip() or len(keyword) > 24 or not re.fullmatch(r"[А-Яа-яЁёA-Za-z_-]+", keyword):
        raise ValueError("CTA_KEYWORD must be a word of up to 24 letters")
    if not template.strip() or len(template) > 350 or any(ord(c) < 32 for c in template + contact):
        raise ValueError("CTA_TEXT and CTA_CONTACT must be short single lines")
    try:
        text = template.format(keyword=keyword, contact=contact).strip()
    except (KeyError, ValueError, IndexError, AttributeError):
        raise ValueError("CTA_TEXT supports only {keyword} and {contact}") from None
    if keyword.casefold() not in text.casefold() or "сохран" not in text.casefold():
        raise ValueError("CTA_TEXT must contain the keyword and a save reminder")
    if _PROMISE.search(text):
        raise ValueError("CTA_TEXT cannot promise a result or a legal victory")
    # Eight seconds at a calm, approximately 2.5 words/second pace.
    if len(text.split()) > 20:
        raise ValueError("CTA_TEXT must fit the last eight seconds (at most 20 words)")
    return text


@dataclass(frozen=True, slots=True)
class SceneCue:
    text: str
    tags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "tags": list(self.tags)}


@dataclass(frozen=True, slots=True)
class EditorialPlan:
    format: str
    hook_variants: tuple[str, ...]
    selected_hook: int
    scenes: tuple[SceneCue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "hook_variants": list(self.hook_variants), "selected_hook": self.selected_hook,
                **({"scenes": [scene.to_dict() for scene in self.scenes]} if self.scenes else {})}


def parse_editorial(value: Any, hook: str, voiceover: str = "") -> EditorialPlan:
    if not isinstance(value, dict) or set(value) not in ({"format", "hook_variants", "selected_hook"}, {"format", "hook_variants", "selected_hook", "scenes"}):
        raise ValueError("editorial requires exactly format, hook_variants, selected_hook")
    variants, selected = value["hook_variants"], value["selected_hook"]
    if value["format"] not in FORMATS:
        raise ValueError("Unknown editorial format")
    if (not isinstance(variants, list) or not 2 <= len(variants) <= 3 or
            any(not isinstance(item, str) or not item.strip() or "\n" in item or len(item.split()) > 8 for item in variants) or
            len(set(item.casefold() for item in variants)) != len(variants)):
        raise ValueError("Provide two or three distinct short hook variants")
    if type(selected) is not int or not 0 <= selected < len(variants) or variants[selected] != hook:
        raise ValueError("selected_hook must identify the exact spoken hook")
    if any(re.match(r"\s*(сегодня|в этом видео|давайте поговорим)", item, re.I) for item in variants):
        raise ValueError("Start hooks with the audience's problem, without introductory words")
    scenes = []
    if "scenes" in value:
        raw = value["scenes"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
            raise ValueError("scenes requires 1–30 ordered fragments")
        if not isinstance(voiceover, str):
            raise ValueError("voiceover must be text")
        cursor, normalized = 0, " ".join(voiceover.split())
        for scene in raw:
            if (not isinstance(scene, dict) or set(scene) != {"text", "tags"} or
                    not isinstance(scene["text"], str) or not scene["text"].strip() or
                    not isinstance(scene["tags"], list) or not 1 <= len(scene["tags"]) <= 4 or
                    any(not isinstance(tag, str) or not re.fullmatch(r"[a-z][a-z_]{0,31}", tag) for tag in scene["tags"])):
                raise ValueError("Scene requires a spoken fragment and 1–4 lowercase tags")
            text = " ".join(scene["text"].split())
            position = normalized.find(text, cursor)
            if position < 0:
                raise ValueError("Scene fragments must occur in voiceover, in order without overlap")
            cursor = position + len(text)
            scenes.append(SceneCue(text, tuple(dict.fromkeys(scene["tags"]))))
    return EditorialPlan(value["format"], tuple(variants), selected, tuple(scenes))


def publication_caption(script: Any, *, music_credit: str = "") -> str:
    """No generated facts are added during packaging: source URLs are copied verbatim."""
    if script.editorial is None and not music_credit:
        return "\n\n".join((script.caption, script.disclaimer, " ".join(script.hashtags)))
    urls = "\n".join(dict.fromkeys(source.url for source in script.sources))
    return "\n\n".join(value for value in (script.caption, urls, script.disclaimer,
                                                  "Музыка: " + music_credit if music_credit else "", " ".join(script.hashtags)) if value)
