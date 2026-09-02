from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 10.0
MAX_WORKERS = 5
USER_AGENT = "Robotics News Agent/1.0"

_META_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*?content=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
_META_RE_REVERSE = re.compile(
    r'<meta\s+[^>]*?content=["\']([^"\']+)["\'][^>]*?(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*>',
    re.IGNORECASE,
)


def _extract_image_url(html: str, page_url: str) -> str | None:
    for pattern in (_META_RE, _META_RE_REVERSE):
        match = pattern.search(html)
        if match:
            candidate = urljoin(page_url, match.group(1).strip())
            if candidate.startswith(("http://", "https://")):
                return candidate
    return None


def fetch_image_url(article_url: str) -> str | None:
    """Find the article's og:image, falling back to twitter:image."""
    try:
        response = httpx.get(
            article_url,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and not response.text.lstrip().lower().startswith("<"):
            return None
        return _extract_image_url(response.text, str(response.url))
    except (httpx.HTTPError, UnicodeError, OSError) as exc:
        logger.warning("Failed to find image for %s: %s", article_url, exc)
        return None


def enrich_with_images(top5: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add image_url to selected stories without making image failures fatal."""
    result = [dict(item) for item in top5]
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(result)))) as executor:
        futures = {
            executor.submit(fetch_image_url, item.get("url", "")): index
            for index, item in enumerate(result)
            if item.get("url")
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                result[index]["image_url"] = future.result()
            except Exception:
                logger.exception("Unexpected image lookup failure for story #%s", index + 1)
                result[index]["image_url"] = None
    return result
