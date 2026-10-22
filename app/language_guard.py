from __future__ import annotations

import re

from app.models import LegalDraft

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _language_ratio(text: str) -> float:
    cyrillic = len(_CYRILLIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    letters = cyrillic + latin
    return cyrillic / letters if letters else 0.0


def validate_russian_text(text: str, *, scope: str, min_ratio: float = 0.45) -> None:
    if _language_ratio(text) < min_ratio:
        raise ValueError(f"{scope} is not sufficiently Russian")


def validate_russian_draft(draft: LegalDraft, *, min_ratio: float = 0.45) -> None:
    """Retain the Cyrillic check without imposing a daily publication format."""
    for field, text in (("title", draft.title), ("intro", draft.intro)):
        if _language_ratio(text) < min_ratio:
            raise ValueError(f"Draft {field} is not sufficiently Russian")
    for index, section in enumerate(draft.sections, start=1):
        for field, text in (("headline", section.headline), ("body", section.body)):
            if _language_ratio(text) < min_ratio:
                raise ValueError(f"Draft section #{index} {field} is not sufficiently Russian")
