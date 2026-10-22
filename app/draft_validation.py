"""Structural and source-grounding checks, not a legal fact-checker."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit

from app.fact_guard import validate_factual_grounding
from app.language_guard import validate_russian_draft
from app.models import LegalDraft, LegalSource


def _require_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")


def _is_source_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


def validate_legal_draft(draft: LegalDraft, sources: Sequence[LegalSource]) -> None:
    if not sources:
        raise ValueError("At least one legal source is required")
    urls: set[str] = set()
    for index, source in enumerate(sources, start=1):
        for field in ("title", "source", "url", "content"):
            _require_text(getattr(source, field), f"Source #{index} {field}")
        if source.jurisdiction != "RU":
            raise ValueError(f"Source #{index} jurisdiction must be RU")
        if not _is_source_url(source.url):
            raise ValueError(f"Source #{index} has an invalid URL")
        if source.url in urls:
            raise ValueError("Duplicate source URLs")
        urls.add(source.url)
    _require_text(draft.title, "Draft title")
    _require_text(draft.intro, "Draft intro")
    if not draft.sections:
        raise ValueError("Draft must contain at least one section")
    for index, section in enumerate(draft.sections, start=1):
        _require_text(section.headline, f"Section #{index} headline")
        _require_text(section.body, f"Section #{index} body")
        if type(section.source_index) is not int or not 1 <= section.source_index <= len(sources):
            raise ValueError(f"Section #{index} has an invalid source_index")
    validate_russian_draft(draft)
    validate_factual_grounding(draft, sources)
