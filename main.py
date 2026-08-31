from datetime import datetime
from pathlib import Path
import os

from app.collector import collect_news
from app.daily_selection import select_top5
from app.article_editor import generate_article, render_markdown, validate_article, OUTPUT_DIR
from app.fallback_article import generate_fallback_article
from app.vk_publisher import publish_to_vk

ALLOWED_TOPICS = {"robotics", "robot_dog", "humanoid", "exoskeleton"}


def _validate_selected_stories(top5):
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
            raise RuntimeError(
                f"TOP-5 story #{index} does not match the four editorial pillars"
            )
        if not topics.issubset(ALLOWED_TOPICS):
            unknown = sorted(topics - ALLOWED_TOPICS)
            raise RuntimeError(
                f"TOP-5 story #{index} contains unsupported topics: {unknown}"
            )
        covered_topics.update(topics.intersection(ALLOWED_TOPICS))

    if len(covered_topics) < 3:
        raise RuntimeError(
            f"TOP-5 topic diversity is too low: {sorted(covered_topics)}; expected at least 3 editorial topics"
        )


def main():
    started_at = datetime.now()
    print("🤖 Robotics News Agent started")

    print("📰 Collecting news...")
    news = collect_news()
    print(f"Collected: {len(news)} items")

    print("🧠 Selecting TOP-5...")
    top5 = select_top5(news)
    print(f"Selected: {len(top5)} stories")
    _validate_selected_stories(top5)
    print("✅ TOP-5 editorial guard passed")

    print("✍ Generating article...")
    try:
        article = generate_article(top5)
    except Exception as exc:
        print(f"⚠️ AI article generation unavailable: {exc}")
        print("📝 Using deterministic article fallback so publishing can continue.")
        article = generate_fallback_article(top5)

    validate_article(article, top5)
    print("✅ Article quality guard passed")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{started_at.strftime('%Y-%m-%d')}.md"
    output_path.write_text(render_markdown(article), encoding="utf-8")
    print(f"FILE CREATED: {output_path.resolve()}")

    required_vk = os.getenv("VK_PUBLISH_REQUIRED", "false").lower() in {"1", "true", "yes"}
    publish_to_vk(article, required=required_vk)

    elapsed = (datetime.now() - started_at).total_seconds()
    print(f"⏱ Pipeline duration: {elapsed:.1f}s")
    print("✅ Pipeline finished")


if __name__ == "__main__":
    main()
