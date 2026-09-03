from __future__ import annotations

import re
from typing import Any

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DAILY_DIGEST_FORBIDDEN = ("неделя", "недели", "неделю", "недельный", "еженедельный")


def _language_ratio(text: str) -> float:
    cyrillic = len(_CYRILLIC_RE.findall(text or ""))
    latin = len(_LATIN_RE.findall(text or ""))
    letters = cyrillic + latin
    return cyrillic / letters if letters else 0.0


def validate_russian_article(article: dict[str, Any], *, min_body_ratio: float = 0.45) -> None:
    """Reject articles whose editorial prose is predominantly non-Russian.

    Company/product names may remain in Latin characters, so the guard uses a
    moderate Cyrillic threshold rather than requiring every word to be Russian.
    """
    title = str(article.get("title") or "")
    intro = str(article.get("intro") or "")
    items = article.get("items") or []

    if _language_ratio(f"{title} {intro}") < 0.45:
        raise ValueError("Article title/intro is not sufficiently Russian")
    if any(term in f"{title} {intro}".casefold() for term in _DAILY_DIGEST_FORBIDDEN):
        raise ValueError("Daily digest must not be framed as a weekly digest")

    for index, item in enumerate(items, start=1):
        body = str(item.get("body") or "")
        if _language_ratio(body) < min_body_ratio:
            raise ValueError(
                f"Article item #{index} is not sufficiently Russian for safe publication"
            )
