from __future__ import annotations

import html
import logging
import re
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 10.0
IMAGE_TIMEOUT = 10.0
MAX_WORKERS = 5
USER_AGENT = "Robotics News Agent/1.0"
MIN_IMAGE_BYTES = 12_000
MIN_IMAGE_WIDTH = 500
MIN_IMAGE_HEIGHT = 300

_META_RE = re.compile(r'<meta\s+[^>]*?(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*?content=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
_META_RE_REVERSE = re.compile(r'<meta\s+[^>]*?content=["\']([^"\']+)["\'][^>]*?(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*>', re.IGNORECASE)
_IMG_RE = re.compile(r'<img\s+[^>]*>', re.IGNORECASE)
_ATTR_RE = re.compile(r'([\w:-]+)=["\']([^"\']+)["\']', re.IGNORECASE)
_SRCSET_RE = re.compile(r'([^,\s]+)(?:\s+\d+[wx])?')
_GENERIC_IMAGE_RE = re.compile(r'(?:^|[/_.-])(logo|icon|avatar|profile|author|placeholder|default|favicon|sprite)(?:[/_.-]|$)', re.IGNORECASE)
_GENERIC_HOST_RE = re.compile(r'(?:unsplash|pexels|pixabay)\.', re.IGNORECASE)


def _normalize_url(candidate: str, page_url: str) -> str | None:
    candidate = html.unescape(candidate).strip()
    if not candidate or candidate.startswith(("data:", "javascript:", "#")):
        return None
    absolute = urljoin(page_url, candidate)
    return absolute if absolute.startswith(("http://", "https://")) else None


def _looks_generic(url: str) -> bool:
    return bool(_GENERIC_IMAGE_RE.search(url) or _GENERIC_HOST_RE.search(url))


def _extract_image_candidates(html_text: str, page_url: str) -> list[tuple[str, int]]:
    """Metadata first, then article <img>/lazy/srcset fallbacks."""
    candidates: list[tuple[str, int]] = []
    for pattern in (_META_RE, _META_RE_REVERSE):
        for match in pattern.finditer(html_text):
            url = _normalize_url(match.group(1), page_url)
            if url:
                candidates.append((url, 100))
    for tag_match in _IMG_RE.finditer(html_text):
        attrs = {key.lower(): value for key, value in _ATTR_RE.findall(tag_match.group(0))}
        for key in ("src", "data-src", "data-original", "data-lazy-src"):
            url = _normalize_url(attrs.get(key, ""), page_url)
            if url:
                candidates.append((url, 80))
        if attrs.get("srcset"):
            for srcset_match in _SRCSET_RE.finditer(attrs["srcset"]):
                url = _normalize_url(srcset_match.group(1), page_url)
                if url:
                    candidates.append((url, 75))
    seen: set[str] = set()
    result: list[tuple[str, int]] = []
    for url, priority in candidates:
        if url in seen:
            continue
        seen.add(url)
        if _looks_generic(url):
            priority -= 60
        result.append((url, priority))
    return sorted(result, key=lambda item: item[1], reverse=True)


def _image_dimensions(content: bytes) -> tuple[int, int] | None:
    """Read JPEG/PNG/WebP dimensions without adding a new dependency."""
    try:
        if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
            return struct.unpack(">II", content[16:24])
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP" and len(content) >= 30 and content[12:16] == b"VP8X":
            return 1 + int.from_bytes(content[24:27], "little"), 1 + int.from_bytes(content[27:30], "little")
        if content.startswith(b"\xff\xd8"):
            index = 2
            while index + 9 < len(content):
                if content[index] != 0xFF:
                    index += 1
                    continue
                marker = content[index + 1]
                index += 2
                if marker in (0xD8, 0xD9):
                    continue
                if index + 2 > len(content):
                    break
                length = int.from_bytes(content[index:index + 2], "big")
                if length < 2 or index + length > len(content):
                    break
                if marker in list(range(0xC0, 0xC4)) + list(range(0xC5, 0xC8)) + list(range(0xC9, 0xCC)) + list(range(0xCD, 0xD0)) and length >= 7:
                    return int.from_bytes(content[index + 5:index + 7], "big"), int.from_bytes(content[index + 3:index + 5], "big")
                index += length
    except (IndexError, struct.error, ValueError):
        pass
    return None


def _validate_image(url: str) -> bool:
    if _looks_generic(url):
        logger.info("Skipping generic image candidate: %s", url)
        return False
    try:
        response = httpx.get(url, timeout=IMAGE_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            return False
        if len(response.content) < MIN_IMAGE_BYTES:
            return False
        dimensions = _image_dimensions(response.content)
        return bool(dimensions and dimensions[0] >= MIN_IMAGE_WIDTH and dimensions[1] >= MIN_IMAGE_HEIGHT)
    except (httpx.HTTPError, UnicodeError, OSError) as exc:
        logger.info("Image candidate rejected %s: %s", url, exc)
        return False


def fetch_image_url(article_url: str) -> str | None:
    """Find a usable article image via metadata, HTML images, lazy images and srcset."""
    try:
        response = httpx.get(article_url, timeout=FETCH_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and not response.text.lstrip().lower().startswith("<"):
            return None
        for url, _priority in _extract_image_candidates(response.text, str(response.url)):
            if _validate_image(url):
                return url
        return None
    except (httpx.HTTPError, UnicodeError, OSError) as exc:
        logger.warning("Failed to find image for %s: %s", article_url, exc)
        return None


def enrich_with_images(top5: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [dict(item) for item in top5]
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(result)))) as executor:
        futures = {executor.submit(fetch_image_url, item.get("url", "")): index for index, item in enumerate(result) if item.get("url")}
        for future in as_completed(futures):
            index = futures[future]
            try:
                result[index]["image_url"] = future.result()
            except Exception:
                logger.exception("Unexpected image lookup failure for story #%s", index + 1)
                result[index]["image_url"] = None
    return result
