"""Intermediate legal text contracts; the video script schema is a later stage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LegalSource:
    title: str
    source: str
    url: str
    content: str
    jurisdiction: str = "RU"


@dataclass(frozen=True, slots=True)
class LegalSection:
    headline: str
    body: str
    source_index: int


@dataclass(frozen=True, slots=True)
class LegalDraft:
    title: str
    intro: str
    sections: tuple[LegalSection, ...]

