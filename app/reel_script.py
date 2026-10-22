"""Strict script contract and checks against the selected topic's source snapshot."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.config import Settings
from app.fact_guard import validate_grounded_text
from app.language_guard import validate_russian_text
from app.primary_evidence import citations
from app.topics import Topic
from app.topic_urls import canonical_url

DISCLAIMER = "Информация носит общий характер и не заменяет индивидуальную юридическую консультацию."
_WORD = re.compile(r"[^\W_]+(?:[-–][^\W_]+)*", re.UNICODE)
_STRING = {"type": "string", "minLength": 1}
_HASHTAG_PATTERN = r"^#[A-Za-zА-Яа-яЁё0-9_]+$"
SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["hook", "voiceover", "on_screen_text", "caption", "hashtags", "sources", "disclaimer"],
    "properties": {
        "hook": dict(_STRING), "voiceover": dict(_STRING), "caption": dict(_STRING),
        "disclaimer": {"type": "string", "enum": [DISCLAIMER]},
        "on_screen_text": {"type": "array", "minItems": 1, "items": dict(_STRING)},
        "hashtags": {"type": "array", "minItems": 1,
                     "items": {"type": "string", "pattern": _HASHTAG_PATTERN}},
        "sources": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "url", "citation"], "properties": {
                "title": dict(_STRING), "url": dict(_STRING),
                "citation": {"type": "string"},
            },
        }},
    },
}


@dataclass(frozen=True, slots=True)
class ScriptSource:
    title: str
    url: str
    citation: str


@dataclass(frozen=True, slots=True)
class ReelScript:
    hook: str
    voiceover: str
    on_screen_text: tuple[str, ...]
    caption: str
    hashtags: tuple[str, ...]
    sources: tuple[ScriptSource, ...]
    disclaimer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hook": self.hook, "voiceover": self.voiceover,
            "on_screen_text": list(self.on_screen_text), "caption": self.caption,
            "hashtags": list(self.hashtags), "sources": [asdict(source) for source in self.sources],
            "disclaimer": self.disclaimer,
        }


def word_count(text: str) -> int:
    """Count words/numbers; a hyphenated word is one word."""
    return len(_WORD.findall(text))


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{field} must be a {'possibly empty' if allow_empty else 'non-empty'} string")
    return value


def _texts(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    return tuple(_text(item, field) for item in value)


def topic_sources(topic: Topic) -> tuple[ScriptSource, ...]:
    """Copy primary citations verbatim; media cards do not invent requisites."""
    if not topic.articles or not topic.references:
        raise ValueError("Selected topic requires articles and primary references")
    sources: list[ScriptSource] = []
    for ref in topic.references:
        if ref.availability_verified is not True or not ref.excerpt.strip() or not ref.citation.strip():
            raise ValueError("Selected topic has an unverified or incomplete primary reference")
        canonical_url(ref.url)
        # The collector has no separate document title: its verbatim citation is the title.
        sources.append(ScriptSource(ref.citation, ref.url, ref.citation))
    for article in topic.articles:
        canonical_url(article.url)
        if not article.title.strip() or not article.text.strip():
            raise ValueError("Selected topic has an empty article")
        sources.append(ScriptSource(article.title, article.url, ""))
    return tuple(dict.fromkeys(sources))


def parse_script(data: dict[str, Any], topic: Topic, settings: Settings) -> ReelScript:
    """Validate every schema field plus length, structure, sources and narrow grounding."""
    if not isinstance(data, dict) or set(data) != set(SCRIPT_SCHEMA["required"]):
        raise ValueError("Script must contain exactly the seven required fields")
    hook = _text(data["hook"], "hook")
    voiceover = _text(data["voiceover"], "voiceover")
    caption = _text(data["caption"], "caption")
    disclaimer = _text(data["disclaimer"], "disclaimer")
    screens = _texts(data["on_screen_text"], "on_screen_text")
    hashtags = _texts(data["hashtags"], "hashtags")
    if any(re.fullmatch(_HASHTAG_PATTERN, tag) is None for tag in hashtags) or len(set(hashtags)) != len(hashtags):
        raise ValueError("hashtags must be unique #words")
    raw_sources = data["sources"]
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("sources must be a non-empty array")
    sources: list[ScriptSource] = []
    for source in raw_sources:
        if not isinstance(source, dict) or set(source) != {"title", "url", "citation"}:
            raise ValueError("Each source requires exactly title, url and citation")
        sources.append(ScriptSource(
            _text(source["title"], "source.title"), _text(source["url"], "source.url"),
            _text(source["citation"], "source.citation", allow_empty=True),
        ))
    if len(sources) != len(set(sources)) or set(sources) != set(topic_sources(topic)):
        raise ValueError("sources must exactly preserve the selected topic's source cards")
    if not 80 <= word_count(voiceover) <= 140:
        raise ValueError("voiceover must contain 80–140 words including hook and CTA")
    if not 1 <= word_count(hook) <= 8 or "\n" in hook or "\r" in hook:
        raise ValueError("hook must be one line of up to eight words (estimated three seconds)")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", voiceover.strip())]
    if len(paragraphs) != 4 or any(not part for part in paragraphs):
        raise ValueError("voiceover requires four paragraphs: hook, essence, actions, CTA")
    if paragraphs[0] != hook or paragraphs[-1].rstrip(".!?…") != settings.script_cta.rstrip(".!?…"):
        raise ValueError("voiceover must start with hook and end with configured CTA")
    if disclaimer != DISCLAIMER:
        raise ValueError("disclaimer must match the required editorial notice")
    evidence = "\n".join([
        *(f"{article.title}\n{article.text}" for article in topic.articles),
        *(f"{ref.citation}\n{ref.excerpt}" for ref in topic.references),
    ])
    texts = {"hook": hook, "voiceover": voiceover, "caption": caption,
             **{f"on_screen_text[{index}]": text for index, text in enumerate(screens)}}
    evidence_citations = {_citation_key(citation) for _, citation, _ in citations(evidence)}
    for field, text in texts.items():
        validate_russian_text(text, scope=field)
        validate_grounded_text(text, evidence, scope=field)
        if any(_citation_key(citation) not in evidence_citations for _, citation, _ in citations(text)):
            raise ValueError(f"{field} contains a citation absent from the selected topic")
    validate_grounded_text(" ".join(hashtags), evidence, scope="hashtags")
    return ReelScript(hook, voiceover, screens, caption, hashtags, tuple(sources), disclaimer)


def _citation_key(value: str) -> str:
    return re.sub(r"\s", "", value.casefold()).replace("–", "-")
