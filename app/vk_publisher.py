from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

VK_API_URL = "https://api.vk.com/method/wall.post"
DEFAULT_API_VERSION = "5.199"
DEFAULT_TIMEZONE = "Europe/Moscow"
DEFAULT_TIMEOUT = 20.0


def render_vk_message(article: dict[str, Any]) -> str:
    """Render the structured article as a clean, readable VK wall post."""
    number_icons = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")
    lines = [
        "🤖 РОБОТОТЕХНИКА — ДАЙДЖЕСТ НЕДЕЛИ",
        "",
        article["title"].strip(),
        "",
        article["intro"].strip(),
    ]

    for index, item in enumerate(article["items"], start=1):
        icon = number_icons[index - 1] if index <= len(number_icons) else f"{index}."
        source = item["source"].strip()
        url = item["url"].strip()
        lines.extend(
            [
                "",
                f"{icon} {item['headline'].strip()}",
                "",
                item["body"].strip(),
                "",
                f"🔗 Источник: {source}",
                url,
            ]
        )

    lines.extend(
        [
            "",
            "—",
            "🤖 Пять событий недели без рекламных обещаний и неподтверждённых выводов.",
        ]
    )
    return "\n".join(lines).strip()


def daily_random_id(article: dict[str, Any]) -> int:
    """Return a deterministic VK random_id for the current publication day."""
    timezone = ZoneInfo(os.getenv("TIMEZONE", DEFAULT_TIMEZONE))
    date_key = datetime.now(timezone).date().isoformat()
    digest = hashlib.sha256(f"robotics-news-agent:{date_key}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _config() -> tuple[str | None, str | None]:
    token = os.getenv("VK_ACCESS_TOKEN") or os.getenv("VK_TOKEN")
    group_id = os.getenv("VK_GROUP_ID")
    return token, group_id


def publish_to_vk(article: dict[str, Any], *, required: bool = False) -> int | None:
    """Publish an article to VK, with bounded retries for transient failures."""
    token, group_id = _config()
    if not token or not group_id:
        message = "VK publication skipped: VK_ACCESS_TOKEN/VK_TOKEN or VK_GROUP_ID is not configured"
        if required:
            raise RuntimeError(message)
        print(f"ℹ️ {message}")
        return None

    try:
        owner_id = -abs(int(group_id))
    except ValueError as exc:
        raise RuntimeError(f"VK_GROUP_ID must be an integer, got {group_id!r}") from exc

    payload = {
        "access_token": token,
        "v": os.getenv("VK_API_VERSION", DEFAULT_API_VERSION),
        "owner_id": owner_id,
        "from_group": 1,
        "message": render_vk_message(article),
        "random_id": daily_random_id(article),
    }

    timeout = float(os.getenv("VK_PUBLISH_TIMEOUT", str(DEFAULT_TIMEOUT)))
    retryable_api_errors = {6, 9, 10, 29}
    last_error: str | None = None

    for attempt in range(2):
        try:
            response = httpx.post(VK_API_URL, data=payload, timeout=timeout)
            if response.status_code in (408, 429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise RuntimeError(last_error)

            response.raise_for_status()
            data = response.json()
            if "error" in data:
                error = data["error"]
                code = int(error.get("error_code", 0))
                last_error = f"VK API error {code}: {error.get('error_msg')}"
                if attempt == 0 and code in retryable_api_errors:
                    time.sleep(1)
                    continue
                raise RuntimeError(last_error)

            post_id = (data.get("response") or {}).get("post_id")
            if not isinstance(post_id, int):
                raise RuntimeError(f"VK API returned unexpected response: {data}")
            print(f"📣 VK publication succeeded: post_id={post_id}, random_id={payload['random_id']}")
            return post_id
        except httpx.HTTPError as exc:
            last_error = str(exc)
            if attempt == 0:
                time.sleep(1)
                continue
            raise RuntimeError(f"VK publication failed after 2 attempts: {last_error}") from exc

    raise RuntimeError(f"VK publication failed after 2 attempts: {last_error}")
