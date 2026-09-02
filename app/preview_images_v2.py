from pathlib import Path
import json

from app.collector import collect_news
from app.daily_selection import select_top5
from app.image_fetcher_v2 import enrich_with_images

ALLOWED_TOPICS = {"robotics", "robot_dog", "humanoid", "exoskeleton"}
TOP5_OUTPUT_PATH = Path("data/latest_top5_images_v2.json")
PREVIEW_OUTPUT_PATH = Path("articles/preview_images_v2.md")


def validate_top5(top5):
    if len(top5) != 5:
        raise RuntimeError(f"Selected {len(top5)} stories; exactly 5 are required")
    urls = [item.get("url") for item in top5]
    if any(not isinstance(url, str) or not url.startswith(("http://", "https://")) for url in urls):
        raise RuntimeError("TOP-5 contains an invalid source URL")
    if len(urls) != len(set(urls)):
        raise RuntimeError("TOP-5 contains duplicate source URLs")
    covered_topics = set()
    for index, item in enumerate(top5, start=1):
        topics = set(item.get("topics") or ())
        if not topics.intersection(ALLOWED_TOPICS):
            raise RuntimeError(f"TOP-5 story #{index} does not match the editorial pillars")
        if not topics.issubset(ALLOWED_TOPICS):
            raise RuntimeError(f"TOP-5 story #{index} contains unsupported topics")
        covered_topics.update(topics.intersection(ALLOWED_TOPICS))
    if len(covered_topics) < 3:
        raise RuntimeError(f"TOP-5 topic diversity is too low: {sorted(covered_topics)}")


def main():
    print("🖼️ Image fallback preview: OpenRouter and VK are disabled")
    news = collect_news()
    print(f"Collected: {len(news)} items")
    top5 = select_top5(news)
    print(f"Selected: {len(top5)} stories")
    validate_top5(top5)
    print("✅ TOP-5 editorial guard passed")
    top5 = enrich_with_images(top5)
    image_count = sum(bool(item.get("image_url")) for item in top5)
    print(f"Validated images found: {image_count}/5")

    TOP5_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOP5_OUTPUT_PATH.write_text(json.dumps(top5, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Preview: validated article images", "", "> OpenRouter and VK are disabled.", ""]
    for index, item in enumerate(top5, start=1):
        lines.extend([
            f"## {index}. {item.get('title', 'Без заголовка')}",
            "",
            f"**Источник:** {item.get('source', 'Источник')}",
            f"**Изображение:** {item.get('image_url') or 'не найдено'}",
            f"**Ссылка:** {item.get('url', '')}",
            "",
        ])
    PREVIEW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"PREVIEW CREATED: {PREVIEW_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
