from __future__ import annotations

import os
import time
from typing import Any

import httpx

VK_API_URL = "https://api.vk.com/method/wall.post"
DEFAULT_API_VERSION = "5.199"


def render_vk_message(article: dict[str, Any]) -> str:
    """Render the structured article as a readable VK wall post."""
    lines = [f"{article['title']}", "", article["intro"], ""]
    for index, item in enumerate(article["items"], start=1):
        lines.extend(
            [
                f"{index}. {item['headline']}",
                item["body"],
                f"Источник: {item['source']}",
                item["url"],
                "",
            ]
        )
    return "\n".join(lines).strip()


def _config() -> tuple[str | None, str | None]:
    token = os.getenv("VK_ACCESS_TOKEN") or os.getenv("VK_TOKEN")
    group_id = os.getenv("VK_GROUP_ID")
    return token, group_id


def publish_to_vk(article: dict[str, Any], *, required: bool = False) -> int | None:
    """Publish an article to the configured VK group.

    Missing VK credentials are a no-op unless ``required`` is true. Network
    failures are retried once for transient errors and then surfaced.
    """
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
    }

    last_error: str | None = None
    for attempt in range(2):
        try:
            response = httpx.post(VK_API_URL, data=payload, timeout=30)
            if response.status_code in (408, 429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                if attempt == 0:
                    time.sleep(2)
                    continue
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                error = data["error"]
                last_error = f"VK API error {error.get('error_code')}: {error.get('error_msg')}"
                if attempt == 0 and int(error.get("error_code", 0)) in {6, 9, 10, 29}:
                    time.sleep(2)
                    continue
                raise RuntimeError(last_error)

            post_id = (data.get("response") or {}).get("post_id")
            if not isinstance(post_id, int):
                raise RuntimeError(f"VK API returned unexpected response: {data}")
            print(f"📣 VK publication succeeded: post_id={post_id}")
            return post_id
        except (httpx.HTTPError, RuntimeError) as exc:
            last_error = str(exc)
            if attempt == 0:
                time.sleep(2)
                continue

    raise RuntimeError(f"VK publication failed after 2 attempts: {last_error}")
