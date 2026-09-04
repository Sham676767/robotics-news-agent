from pathlib import Path
import json

from app.collector import collect_news
from app.daily_selection import select_top5
from app.image_fetcher import enrich_with_images

ALLOWED_TOPICS = {"robotics", "robot_dog", "humanoid", "exoskeleton"}
TOP5_OUTPUT_PATH = Path("data/latest_top5.json")
PREVIEW_OUTPUT_PATH = Path("articles/preview.md")


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
    # Match the production guard: keep variety, but permit a quiet
    # editorial pillar when five distinct current stories are available.
    if len(covered_topics) < 2:
        raise RuntimeError(f"TOP-5 topic diversity is too low: {sorted(covered_topics)}")


def render_preview(top5):
    lines = [
        "# Предпросмотр TOP-5 Robotics News Agent",
        "",
        "> Это предпросмотр реальных карточек после отбора. OpenRouter и VK не запускаются.",
        "",
    ]
    for index, item in enumerate(top5, start=1):
        title = str(item.get("title") or "Без заголовка").strip()
        source = str(item.get("source") or item.get("publisher") or "Источник").strip()
        summary = str(item.get("summary") or "").strip()
        url = str(item.get("url") or "").strip()
        published_at = str(item.get("published_at") or "").strip()
        language = str(item.get("language") or "").strip()
        topics = ", ".join(str(x) for x in (item.get("topics") or []))
        image_url = str(item.get("image_url") or "").strip()
        lines.extend([
            f"## {index}. {title}",
            "",
            f"**Источник:** {source}",
            f"**Дата:** {published_at or 'не указана'}",
            f"**Язык:** {language or 'не указан'}",
            f"**Темы:** {topics or 'не указаны'}",
            "",
            summary or "_Краткое описание отсутствует._",
            "",
            f"**Ссылка:** {url}",
            f"**Изображение:** {image_url or 'не найдено'}",
            "",
        ])
    return "\n".join(lines)


def main():
    print("👀 Preview mode: OpenRouter and VK are disabled")
    print("📰 Collecting news...")
    news = collect_news()
    print(f"Collected: {len(news)} items")
    print("🧠 Selecting TOP-5...")
    top5 = select_top5(news)
    print(f"Selected: {len(top5)} stories")
    validate_top5(top5)
    print("✅ TOP-5 editorial guard passed")
    print("🖼️ Finding source images...")
    top5 = enrich_with_images(top5)
    image_count = sum(bool(item.get("image_url")) for item in top5)
    print(f"Images found: {image_count}/5")

    TOP5_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOP5_OUTPUT_PATH.write_text(json.dumps(top5, ensure_ascii=False, indent=2), encoding="utf-8")
    PREVIEW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_OUTPUT_PATH.write_text(render_preview(top5), encoding="utf-8")
    print(f"PREVIEW CREATED: {PREVIEW_OUTPUT_PATH}")
    print("✅ Preview finished; no AI generation or publication was attempted")


if __name__ == "__main__":
    main()
