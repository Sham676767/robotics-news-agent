"""Conservative extraction of explicit identifiers; never infer missing numbers."""
from __future__ import annotations

import re
from dataclasses import dataclass

_N = r"\d+(?:\.\d+)*"
_PART = rf"(?:ч\.|част[ьи])\s*(?P<part>{_N})\s*[,;]?\s*"
_ARTICLE = rf"(?:ст\.|стать[яиюе])\s*(?P<article>{_N})\s*"
_LAW = r"(?P<law>(?:ГК|НК|ТК|ЖК|СК|УК|ГПК|АПК|КАС|КоАП)\s+РФ|\d{1,5}[-–](?:ФКЗ|ФЗ))"
_LAW_PREFIX = r"(?:Федерального\s+(?:конституционного\s+)?закона\s+(?:от\s+\d{2}\.\d{2}\.\d{4}\s+)?(?:№\s*)?)?"
_NORM = re.compile(rf"(?<!\w)(?:{_PART})?{_ARTICLE}{_LAW_PREFIX}{_LAW}\b", re.I)
_MENTIONS = (
    ("article", re.compile(rf"(?<!\w)(?:ст\.|стать[яиюе])\s*({_N})(?!\d)", re.I)),
    ("part", re.compile(rf"(?<!\w)(?:ч\.|част[ьи])\s*({_N})(?!\d)", re.I)),
    ("case", re.compile(r"\b[АA]\d{1,3}[-–]\d{1,9}/\d{2,4}\b", re.I)),
    ("case", re.compile(r"\b\d{1,3}[-–][А-ЯЁ]{1,5}\d{0,4}[-–]\d{1,8}(?:/\d{2,4})?\b", re.I)),
    ("case", re.compile(r"(?:дел[оауы]|деле)\s*№?\s*([\dА-ЯA-Z][\w./–-]*\d)", re.I)),
    ("law", re.compile(r"\b\d{1,5}[-–](?:ФКЗ|ФЗ)\b", re.I)),
)


def reference_key(value: str) -> str:
    return re.sub(r"\s", "", value.casefold()).replace("–", "-")


@dataclass(frozen=True, slots=True)
class Norm:
    law: str
    article: str
    part: str

    def key(self) -> tuple[str, str, str]:
        return reference_key(self.law), self.article, self.part


def explicit_norms(text: str) -> tuple[Norm, ...]:
    return tuple(dict.fromkeys(Norm(match["law"], match["article"], match["part"] or "")
                               for match in _NORM.finditer(text)))


def identifier_tokens(text: str) -> set[tuple[str, str]]:
    return {(kind, reference_key(match.group(1) if pattern.groups else match.group()))
            for kind, pattern in _MENTIONS for match in pattern.finditer(text)}
