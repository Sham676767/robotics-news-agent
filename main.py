from datetime import datetime
from pathlib import Path

from app.collector import collect_news
from app.daily_selection import select_top5
from app.article_editor import generate_article, render_markdown, OUTPUT_DIR


def main():
    print("🤖 Robotics News Agent started")

    print("📰 Collecting news...")
    news = collect_news()

    print(f"Collected: {len(news)} items")

    print("🧠 Selecting TOP-5...")
    top5 = select_top5(news)

    print(f"Selected: {len(top5)} stories")

    print("✍ Generating article...")
    article = generate_article(top5)

    print("Article generated:")
    print(str(article)[:500])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"

    output_path.write_text(
        render_markdown(article),
        encoding="utf-8"
    )

    print(f"FILE CREATED: {output_path.resolve()}")
    print("✅ Pipeline finished")


if __name__ == "__main__":
    main()
