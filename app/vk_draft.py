from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.vk_publisher import render_vk_message


def build_vk_draft(article: dict[str, Any]) -> dict[str, Any]:
    """Build a review-only VK payload without contacting the VK API."""
    image_sources: list[dict[str, Any]] = []
    for index, item in enumerate(article.get("items") or [], start=1):
        image_url = item.get("image_url")
        if isinstance(image_url, str) and image_url.startswith(("https://", "http://")):
            image_sources.append(
                {
                    "item_index": index,
                    "headline": str(item.get("headline") or ""),
                    "image_url": image_url,
                    "source_url": str(item.get("url") or ""),
                }
            )

    return {
        "status": "review_required",
        "publication_performed": False,
        "message": render_vk_message(article),
        "image_sources": image_sources,
        "note": (
            "Это черновик. Изображения перечислены как исходные URL и не были "
            "загружены в VK. Публикация возможна только отдельным подтверждённым запуском."
        ),
    }


def write_vk_draft(article: dict[str, Any], output_path: Path) -> Path:
    output_path.write_text(
        json.dumps(build_vk_draft(article), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path
