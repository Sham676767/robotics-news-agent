from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 10.0
MAX_WORKERS = 5
USER_AGENT = "Robotics News Agent/1.0"
MIN_IMAGE_BYTES = 12_000
MIN_IMAGE_WIDTH = 320
MIN_IMAGE_HEIGHT = 180

_META_RE = re.compile(
    r'<meta\s+[^>]*?(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*?content=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
_META_RE_REVERSE = re.compile(
    r'<meta\s+[^>]*?content=["\']([^"\']+)["\'][^>]*?(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*>',
    re.IGNORECASE,
)
_IMG_RE = re.compile(r'<img\s+[^>]*?(?:src|data-src)=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
_SRCSET_RE = re.compile(r'(?:srcset|data-srcset)=["\']([^"\']+)["\']', re.IGNORECASE)
_BAD_IMAGE_WORDS = re.compile(r'(?:logo|avatar|icon|favicon|placeholder|sprite|emoji|gravatar)', re.IGNORECASE)
_BAD_IMAGE_HOSTS = re.compile(r'(?:unsplash\.com|images\.pexels\.com|pexels\.com)', re.IGNORECASE)


def _normalise_candidate(value: str, page_url: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value.startswith("//"):
        value = "https:" + value
    candidate = urljoin(page_url, value)
    if not candidate.startswith(("http://", "https://")):
        return None
    return candidate


def _extract_candidates(html: str, page_url: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = _normalise_candidate(value, page_url)
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    for pattern in (_META_RE, _META_RE_REVERSE):
        for match in pattern.finditer(html):
            add(match.group(1))

    for match in _IMG_RE.finditer(html):
        add(match.group(1))

    for match in _SRCSET_RE.finditer(html):
        entries = [part.strip().split()[0] for part in match.group(1).split(",") if part.strip()]
        for value in reversed(entries):
            add(value)

    return candidates


def _looks_bad(candidate: str) -> bool:
    parsed = urlparse(candidate)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    return bool(_BAD_IMAGE_WORDS.search(path) or _BAD_IMAGE_HOSTS.search(host))


def _valid_image_url(candidate: str) -> bool:
    if _looks_bad(candidate):
        return False
    try:
        response = httpx.get(
            candidate,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/jpeg,image/png,image/*;q=0.8"},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith(("image/jpeg", "image/png", "image/webp")):
            return False
        if len(response.content) < MIN_IMAGE_BYTES:
            return False
        width = height = None
        try:
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(response.content)) as image:
                width, height = image.size
        except Exception:
            return False
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            return False
        return True
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.debug("Rejected image %s: %s", candidate, exc)
        return False


def fetch_image_url(article_url: str) -> str | None:
    """Find the first usable article image using metadata, HTML images and srcset."""
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
        candidates = _extract_candidates(response.text, str(response.url))
        for candidate in candidates:
            if _valid_image_url(candidate):
                return candidate
        return None
    except (httpx.HTTPError, UnicodeError, OSError) as exc:
        logger.warning("Failed to find image for %s: %s", article_url, exc)
        return None


def enrich_with_images(top5: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add validated image_url to selected stories without making image failures fatal."""
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
