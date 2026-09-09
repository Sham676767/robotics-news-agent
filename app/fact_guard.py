from __future__ import annotations

import re
from typing import Any

# Capture both decimal notation (``1.8`` / ``1,8``) and grouped thousands
# notation (``5,000`` / ``5 000``).  Russian editorial text commonly replaces
# the comma in an English source with a space, which must not look like a new
# factual claim.
_NUMBER_RE = re.compile(
    r"(?<!\d)(?:\d{1,3}(?:[ \u00A0\u202F.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?!\d)"
)
# Publication timestamps are part of each source card and may be used as dates.
# URLs and image metadata are excluded because incidental digits are not evidence.
_SOURCE_FIELDS = (
    "title",
    "summary",
    "description",
    "content",
    "published_at",
    "published",
    "date",
)

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


def _canonical_number(value: str) -> str:
    """Normalize decimal and thousands separators without changing magnitude."""
    compact = re.sub(r"[ \u00A0\u202F]", "", value)
    separators = [char for char in compact if char in ".,"]
    if not separators:
        return compact

    # With both separators, the rightmost one is decimal only when it has a
    # short fractional part: 1,800.50 and 1.800,50 both mean 1800.5.
    if "." in compact and "," in compact:
        decimal_at = max(compact.rfind("."), compact.rfind(","))
        fraction = compact[decimal_at + 1 :]
        if 1 <= len(fraction) <= 2:
            integer = re.sub(r"[.,]", "", compact[:decimal_at])
            return _trim_decimal(integer, fraction)
        return re.sub(r"[.,]", "", compact)

    separator = separators[0]
    parts = compact.split(separator)
    # ``5,000`` and ``5.000`` are grouped thousands; a one- or two-digit last
    # part is a decimal, as in ``1,8`` and ``13.5``.
    if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
        return "".join(parts)
    if len(parts) == 2:
        return _trim_decimal(parts[0], parts[1])
    return compact.replace(separator, "")


def _trim_decimal(integer: str, fraction: str) -> str:
    fraction = fraction.rstrip("0")
    return f"{integer}.{fraction}" if fraction else integer


def _numbers(text: str) -> set[str]:
    return {_canonical_number(value) for value in _NUMBER_RE.findall(text or "")}


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

    This deliberately narrow check verifies numeric claims against the matching
    source card and blocks recurring unsupported embellishments. It does not try
    to translate or fact-check every Russian sentence.
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
