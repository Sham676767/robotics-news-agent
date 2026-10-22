"""Extract citations verbatim; require an available direct official document URL."""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from app.source_http import SourceFetcher, SourceFetchError
from app.topics import Article, PrimaryReference
from app.topic_urls import canonical_url, trusted_host

logger = logging.getLogger(__name__)
CITATIONS = (
    ("law", re.compile(r"\b\d{1,5}[-–](?:ФКЗ|ФЗ)\b", re.I)),
    ("case", re.compile(r"\b[АA]\d{1,3}[-–]\d{1,9}/\d{2,4}\b", re.I)),
    ("case", re.compile(r"\b\d{1,3}[-–][А-ЯЁ]{1,5}\d{0,4}[-–]\d{1,8}(?:/\d{2,4})?\b", re.I)),
    ("article", re.compile(r"(?:стать[яиюе]|ст\.)\s*\d+(?:\.\d+)*\s*(?:ГК|НК|ТК|ЖК|СК|УК|ГПК|АПК|КАС|КоАП)\s*РФ", re.I)),
    ("document", re.compile(r"(?:постановлени[ея]|определени[ея]|приказ[а]?)\s+(?:[^№\n]{0,120})№\s*[\wА-Яа-я/.-]+", re.I)),
)


def is_document_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return bool(re.search(r"(?:/document/\d|/bill/\d|/decision/|/doc/|/documents/[^/]+|/files/\d|/stor_pdf\.php|\.pdf$|/docs/[^/]+)", path))


def citations(text: str) -> list[tuple[str, str, str]]:
    result = []
    for kind, pattern in CITATIONS:
        for match in pattern.finditer(text):
            result.append((kind, match.group(), text[max(0, match.start() - 100):match.end() + 120]))
    return list(dict.fromkeys(result))


def _key(text: str) -> str:
    return re.sub(r"\s", "", text.casefold()).replace("–", "-").replace("№", "")


def find_primary_references(articles: tuple[Article, ...], hosts: tuple[str, ...], fetcher: SourceFetcher) -> tuple[PrimaryReference, ...]:
    result: list[PrimaryReference] = []
    for article in articles:
        extracted = citations(f"{article.title}\n{article.text}")
        if not extracted:
            continue
        urls = [article.url, *(link.url for link in article.links)]
        # A homepage or another news item is not the legal primary document.
        urls = list(dict.fromkeys(url for url in urls if trusted_host(url, hosts) and is_document_url(url)))
        for url in urls[:5]:
            try:
                page = fetcher.fetch(url)
            except SourceFetchError as exc:
                logger.warning("Primary document unavailable: %s (%s)", url, exc)
                continue
            if not trusted_host(page.url, hosts) or not is_document_url(page.url):
                continue
            from bs4 import BeautifulSoup
            primary_text = BeautifulSoup(page.text, "html.parser").get_text(" ", strip=True)
            for kind, citation, excerpt in extracted:
                # HTML must expose the citation. For a directly linked PDF we
                # retain the publisher's verbatim citation and verify availability
                # only; the document's legal content still requires review.
                if "pdf" not in page.content_type.lower() and _key(citation) not in _key(primary_text):
                    continue
                result.append(PrimaryReference(kind, citation, canonical_url(page.url), excerpt, True))
    return tuple(dict.fromkeys(result))
