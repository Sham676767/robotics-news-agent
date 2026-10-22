from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {"fbclid", "gclid", "yclid", "ysclid", "erid", "_openstat"}


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Expected a public HTTP(S) URL without credentials")
    if any(char.isspace() for char in value):
        raise ValueError("URL contains whitespace")
    host = parsed.hostname.lower()
    port = parsed.port
    netloc = f"[{host}]" if ":" in host else host
    if port and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
        netloc += f":{port}"
    query = sorted((key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                   if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS)
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", urlencode(query), ""))


def url_key(value: str) -> str:
    """Identity ignores the final slash; the actual fetch URL preserves it."""
    parsed = urlsplit(canonical_url(value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", parsed.query, ""))


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def trusted_host(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in hosts)
