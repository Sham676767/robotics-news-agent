from __future__ import annotations

import re
from collections.abc import Sequence

from app.models import LegalDraft, LegalSource

# Capture both decimal notation (``1.8`` / ``1,8``) and grouped thousands
# notation (``5,000`` / ``5 000``).  Russian editorial text commonly replaces
# the comma in an English source with a space, which must not look like a new
# factual claim.
_NUMBER_RE = re.compile(
    r"(?<!\d)(?:\d{1,3}(?:[ \u00A0\u202F.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?!\d)"
)
_UNSUPPORTED_EMBELLISHMENTS = (
    "в реальном времени",
    "готовую архитектуру",
    "широкое внимание",
    "важным этапом",
    "ключевым шагом",
    "активным прогрессом",
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


def _source_text(sources: Sequence[LegalSource]) -> str:
    # URLs and publisher names can contain incidental digits: exclude them.
    return " ".join(f"{source.title} {source.content}" for source in sources)


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
            f"{scope} contains numbers absent from its source material: {values}"
        )


def validate_factual_grounding(draft: LegalDraft, sources: Sequence[LegalSource]) -> None:
    """Detect numeric additions and unsupported emphasis, not legal validity.

    This narrow check cannot verify article identifiers, current wording of law,
    jurisdiction, applicability or semantic accuracy. Manual review is required.
    """
    _validate_editorial_text(
        f"{draft.title} {draft.intro}", _source_text(sources), scope="Draft title/intro",
    )
    for index, section in enumerate(draft.sections, start=1):
        if type(section.source_index) is not int or not 1 <= section.source_index <= len(sources):
            raise ValueError(f"Draft section #{index} has no matching source")
        _validate_editorial_text(
            f"{section.headline} {section.body}",
            _source_text([sources[section.source_index - 1]]),
            scope=f"Draft section #{index}",
        )
