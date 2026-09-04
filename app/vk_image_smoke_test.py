from __future__ import annotations

import json
import os
from pathlib import Path

from app.vk_media import VKMediaError, upload_article_images

TOP5_PATH = Path("data/latest_top5.json")


def main() -> None:
    token = os.getenv("VK_ACCESS_TOKEN") or os.getenv("VK_TOKEN")
    group_id = os.getenv("VK_GROUP_ID")
    if not token or not group_id:
        raise RuntimeError("VK_ACCESS_TOKEN/VK_TOKEN and VK_GROUP_ID are required")

    top5 = json.loads(TOP5_PATH.read_text(encoding="utf-8"))
    image_items = [
        item for item in top5
        if isinstance(item.get("image_url"), str)
        and item["image_url"].startswith(("https://", "http://"))
    ][:3]
    if len(image_items) != 3:
        raise RuntimeError(
            f"Exactly three validated source images are required for this test; found {len(image_items)}"
        )

    article = {"items": image_items}
    outcomes: list[dict] = []
    report = {
        "publication_performed": False,
        "wall_post_called": False,
        "requested_images": len(image_items),
        "outcomes": outcomes,
    }
    try:
        attachments = upload_article_images(
            article,
            token=token,
            group_id=group_id,
            outcomes=outcomes,
            stop_on_failure=True,
        )
        report["attachment_ids"] = attachments
    except (VKMediaError, RuntimeError) as exc:
        report["error"] = str(exc)
        print("VK_IMAGE_TEST_REPORT=" + json.dumps(report, ensure_ascii=False))
        raise

    print("VK_IMAGE_TEST_REPORT=" + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
