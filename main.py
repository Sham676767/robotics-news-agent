from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import time

from app.collector import collect_news
from app.daily_selection import select_top5
from app.article_editor import generate_article, render_markdown, validate_article, _normalize_article, OUTPUT_DIR
from app.image_fetcher import enrich_with_images
from app.fact_guard import validate_factual_grounding
from app.language_guard import validate_russian_article
from app.vk_publisher import publish_to_vk
from app.vk_draft import write_vk_draft

CORE_TOPICS = {"robotics", "robot_dog", "humanoid", "exoskeleton"}
ALLOWED_TOPICS = set(CORE_TOPICS)
TOP5_OUTPUT_PATH = Path("data/latest_top5.json")


def _validate_selected_stories(stories):
    if len(stories) != 5:
        raise RuntimeError(f"Selected {len(stories)} stories; expected exactly 5")

    urls = [item.get("url") for item in stories]
    if any(not isinstance(url, str) or not url.startswith(("http://", "https://")) for url in urls):
        raise RuntimeError("Selected stories contain an invalid source URL")
    if len(urls) != len(set(urls)):
        raise RuntimeError("Selected stories contain duplicate source URLs")

    for index, item in enumerate(stories, start=1):
        topics = set(item.get("topics") or ())
        if not topics.intersection(ALLOWED_TOPICS):
            raise RuntimeError(f"Story #{index} does not match an editorial pillar")
        if not topics.issubset(ALLOWED_TOPICS):
            unknown = sorted(topics - ALLOWED_TOPICS)
            raise RuntimeError(f"Story #{index} contains unsupported topics: {unknown}")
def _timed(label, func):
    started = time.perf_counter()
    try:
        return func()
    finally:
        print(f"⏱ {label}: {time.perf_counter() - started:.1f}s")


def _validate_article_quality(article, top5):
    normalized_article = _normalize_article(article)
    validate_article(normalized_article, top5)
    validate_factual_grounding(normalized_article, top5)
    validate_russian_article(article)


def _vk_publication_enabled() -> bool:
    return os.getenv("VK_PUBLISH_ENABLED", "false").lower() in {"1", "true", "yes"}


def _wait_for_vk_publication_window():
    not_before = os.getenv("VK_PUBLISH_NOT_BEFORE_MSK", "").strip()
    if not not_before:
        return

    try:
        publish_time = datetime.strptime(not_before, "%H:%M").time()
    except ValueError as exc:
        raise RuntimeError("VK_PUBLISH_NOT_BEFORE_MSK must use HH:MM format") from exc

    now = datetime.now(ZoneInfo("Europe/Moscow"))
    target = now.replace(hour=publish_time.hour, minute=publish_time.minute, second=0, microsecond=0)
    wait_seconds = (target - now).total_seconds()
    if wait_seconds > 0:
        print(f"⏳ Publication prepared; waiting until {not_before} MSK")
        time.sleep(wait_seconds)


def main():
    pipeline_started = time.perf_counter()
    started_at = datetime.now()
    print("🤖 Robotics News Agent started")

    print("📰 Collecting news...")
    news = _timed("News collection", collect_news)
    print(f"Collected: {len(news)} items")

    print("🧠 Selecting TOP-5...")
    top5 = _timed("TOP-5 selection", lambda: select_top5(news))
    print(f"Selected: {len(top5)} stories")
    _validate_selected_stories(top5)
    print("✅ TOP-5 editorial guard passed")

    print("🖼️ Finding source images...")
    top5 = _timed("Image discovery", lambda: enrich_with_images(top5))
    image_count = sum(bool(item.get("image_url")) for item in top5)
    print(f"Images found: {image_count}/{len(top5)}")

    TOP5_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOP5_OUTPUT_PATH.write_text(json.dumps(top5, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"TOP-5 STATE CREATED: {TOP5_OUTPUT_PATH.resolve()}")

    print("✍ Generating article with OpenRouter...")
    article_started = time.perf_counter()
    try:
        article = generate_article(top5)
    except Exception as exc:
        print(f"❌ AI article generation unavailable: {exc}")
        print("🛑 Publication aborted: an AI-generated article is required.")
        raise RuntimeError("AI article generation failed; refusing to publish fallback content") from exc
    finally:
        print(f"⏱ Article generation: {time.perf_counter() - article_started:.1f}s")

    _timed("Article quality validation", lambda: _validate_article_quality(article, top5))
    print("✅ Article quality guard passed")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{started_at.strftime('%Y-%m-%d')}.md"
    output_path.write_text(render_markdown(article), encoding="utf-8")
    vk_draft_path = output_path.with_suffix(".vk-draft.json")
    write_vk_draft(article, vk_draft_path)
    print(f"FILE CREATED: {output_path.resolve()}")
    print(f"VK DRAFT CREATED: {vk_draft_path.resolve()}")

    if _vk_publication_enabled():
        required_vk = os.getenv("VK_PUBLISH_REQUIRED", "false").lower() in {"1", "true", "yes"}
        _wait_for_vk_publication_window()
        _timed("VK publication", lambda: publish_to_vk(article, required=required_vk))
    else:
        print("ℹ️ VK publication is disabled; article saved for editorial review.")

    print(f"⏱ Pipeline duration: {time.perf_counter() - pipeline_started:.1f}s")
    print("✅ Pipeline finished")


if __name__ == "__main__":
    main()
