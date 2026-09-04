from __future__ import annotations

import re
from typing import Any

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_SOURCE_FIELDS = ("title", "summary", "description", "content")

# These are generic embellishments that free models repeatedly added to drafts
# despite their absence from the supplied source cards. They are unsuitable for
# automatic publication because they turn a reported fact into an unsupported
# technical or market claim.
_UNSUPPORTED_EMBELLISHMENTS = (
    "в реальном времени",
    "готовую архитектуру",
    "широкое внимание",
    "важным этапом",
    "ключевым шагом",
    "активным прогрессом",
    "агрессивные маневры",
    "между роботами и людьми",
    "коммерческую зрелость",
    "лидерство в отрасли",
    "меняет правила игры",
    "новую эру",
    "новый стандарт",
    "безусловное лидерство",
    "не имеющий аналогов",
    "без аналогов",
    "переломным моментом",
)


def _numbers(text: str) -> set[str]:
    return {value.replace(",", ".") for value in _NUMBER_RE.findall(text or "")}


def _source_text(cards: list[dict[str, Any]]) -> str:
    return " ".join(
        str(card.get(field) or "")
        for card in cards
        for field in _SOURCE_FIELDS
    )


def _validate_editorial_text(
    text: str, source_text: str, *, scope: str
) -> None:
    normalized = text.casefold()
    for phrase in _UNSUPPORTED_EMBELLISHMENTS:
        if phrase in normalized:
            raise ValueError(
                f"{scope} contains unsupported embellishment: {phrase!r}"
            )

    unsupported_numbers = _numbers(text) - _numbers(source_text)
    if unsupported_numbers:
        values = ", ".join(sorted(unsupported_numbers))
        raise ValueError(
            f"{scope} contains numbers absent from its source card: {values}"
        )


def validate_factual_grounding(article: dict[str, Any], top5: list[dict[str, Any]]) -> None:
    """Reject obvious factual additions before a draft can be published.

    This is deliberately narrow: it verifies exact numeric claims against the
    corresponding source card and blocks recurring unsupported embellishments.
    It does not try to translate or fact-check every Russian sentence.
    """
    digest_text = f"{article.get('title', '')} {article.get('intro', '')}"
    _validate_editorial_text(
        digest_text,
        _source_text(top5),
        scope="Article title/intro",
    )

    items = article.get("items") or []
    for index, item in enumerate(items, start=1):
        card_index = item.get("card_index", index)
        if not isinstance(card_index, int) or not 1 <= card_index <= len(top5):
            raise ValueError(f"Article item #{index} has no matching source card")

        card = top5[card_index - 1]
        editorial_text = f"{item.get('headline', '')} {item.get('body', '')}"
        _validate_editorial_text(
            editorial_text,
            _source_text([card]),
            scope=f"Article item #{index}",
        )
