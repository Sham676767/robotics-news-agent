from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

GIGACHAT_API_URL = "https://api.giga.chat/v1/chat/completions"
GIGACHAT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
DEFAULT_TIMEOUT = 120.0
RETRYABLE_STATUSES = {408, 409, 429, 500, 502, 503, 504}


class GigaChatError(RuntimeError):
    """Raised when GigaChat cannot return a usable completion."""


def _authorization_header(credentials: str) -> str:
    value = credentials.strip()
    return value if value.lower().startswith("basic ") else f"Basic {value}"


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 60.0))
            except ValueError:
                pass
    base = float(os.getenv("GIGACHAT_RETRY_BASE_SECONDS", "2"))
    maximum = float(os.getenv("GIGACHAT_RETRY_MAX_SECONDS", "20"))
    return min(maximum, base * (2**attempt))


def get_access_token(credentials: str, *, scope: str | None = None, timeout: float = 30.0) -> str:
    """Exchange the stored authorization key for a short-lived API token.

    The authorization key remains the only long-lived GigaChat secret. The
    returned token is intentionally kept in memory only and never logged.
    """
    selected_scope = scope or os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    response = httpx.post(
        os.getenv("GIGACHAT_OAUTH_URL", GIGACHAT_OAUTH_URL),
        headers={
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": _authorization_header(credentials),
        },
        data={"scope": selected_scope},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise GigaChatError("GigaChat OAuth response did not contain access_token")
    return token


def request_completion(
    payload: dict[str, Any],
    *,
    credentials: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Send a Chat Completions request with bounded retries.

    A fresh access token is obtained for every bounded request attempt. This
    keeps a scheduled job independent from expired 30-minute bearer tokens.
    """
    key = credentials or os.getenv("GIGACHAT_AUTHORIZATION_KEY")
    if not key:
        raise GigaChatError("GIGACHAT_AUTHORIZATION_KEY is not configured")

    max_attempts = max(1, int(os.getenv("GIGACHAT_MAX_ATTEMPTS", "2")))
    last_error: str | None = None
    for attempt in range(max_attempts):
        response: httpx.Response | None = None
        try:
            token = get_access_token(key, timeout=min(timeout, 30.0))
            response = httpx.post(
                os.getenv("GIGACHAT_API_URL", GIGACHAT_API_URL),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            if response.status_code in RETRYABLE_STATUSES:
                last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                if attempt + 1 < max_attempts:
                    delay = _retry_delay(response, attempt)
                    print(f"⚠️ GigaChat transient HTTP {response.status_code}; retry {attempt + 2}/{max_attempts} in {delay:.1f}s")
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise GigaChatError("GigaChat returned a non-object response")
            return data
        except (httpx.HTTPError, ValueError, GigaChatError) as exc:
            last_error = str(exc)
            if attempt + 1 < max_attempts:
                delay = _retry_delay(response, attempt)
                print(f"⚠️ GigaChat request error; retry {attempt + 2}/{max_attempts} in {delay:.1f}s: {last_error}")
                time.sleep(delay)
                continue
    raise GigaChatError(f"GigaChat request failed after {max_attempts} attempts: {last_error}")
