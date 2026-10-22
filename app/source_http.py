"""Bounded public-source downloads with TLS verification left enabled."""
from __future__ import annotations

import logging
import time
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.source_config import CollectionConfig
from app.topic_urls import trusted_host

logger = logging.getLogger(__name__)
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}


class SourceFetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    text: str
    content_type: str


class SourceFetcher:
    def __init__(self, config: CollectionConfig) -> None:
        self.config = config
        self.cache: dict[str, FetchedPage] = {}
        self.failures: dict[str, str] = {}
        self.allowed_hosts = tuple(dict.fromkeys((*config.primary_hosts, *(
            urlsplit(source.url).hostname or "" for source in config.sources
        ))))
        self.client = httpx.Client(
            timeout=config.fetch_timeout, follow_redirects=True,
            headers={"User-Agent": "LegalReelsAgent/0.3 (+public legal topic collection)"},
            event_hooks={"request": [self._check_destination]},
        )

    def _check_destination(self, request: httpx.Request) -> None:
        # Applies to redirects as well: feed links must not turn into arbitrary
        # internal-resource fetches later sent to the semantic provider.
        if not trusted_host(str(request.url), self.allowed_hosts):
            raise SourceFetchError("Destination is outside configured source/primary hosts")

    def __enter__(self) -> SourceFetcher:
        return self

    def __exit__(self, *args: object) -> None:
        self.client.close()

    def fetch(self, url: str) -> FetchedPage:
        if url in self.cache:
            return self.cache[url]
        if url in self.failures:
            raise SourceFetchError(self.failures[url])
        reason = "unavailable"
        for attempt in range(self.config.fetch_attempts):
            retryable = False
            try:
                with self.client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        reason = f"HTTP {response.status_code}"
                        retryable = response.status_code in RETRYABLE_STATUSES
                    else:
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > self.config.max_response_bytes:
                                raise SourceFetchError("Response exceeds max_response_bytes")
                        content_type = response.headers.get("content-type", "")
                        if "pdf" in content_type.lower() and not content.startswith(b"%PDF-"):
                            raise SourceFetchError("Invalid PDF response")
                        if content.startswith(b"%PDF-"):
                            content_type = "application/pdf"
                        # Binary documents are checked for availability, not parsed as legal text.
                        encoding = response.charset_encoding
                        if encoding is None:
                            declared = re.search(br'<\?xml[^>]*encoding=[\'"]([^\'"]+)', bytes(content[:200]))
                            encoding = declared.group(1).decode("ascii") if declared else "utf-8"
                        text = "" if "pdf" in content_type.lower() else bytes(content).decode(encoding, errors="replace")
                        page = FetchedPage(str(response.url), text, content_type)
                        self.cache[url] = page
                        return page
            except (httpx.HTTPError, UnicodeError, LookupError) as exc:
                reason = type(exc).__name__
                retryable = True
            except SourceFetchError as exc:
                reason = str(exc)
            if retryable and attempt + 1 < self.config.fetch_attempts:
                logger.warning("Source fetch retry %d/%d: %s", attempt + 2, self.config.fetch_attempts, reason)
                time.sleep(min(2 ** attempt, 4))
                continue
            break
        self.failures[url] = reason
        raise SourceFetchError(reason)
