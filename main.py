from app.collector import collect_news
from app.daily_selection import select_top5
from app.article_editor import generate_article


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

    print("✅ Pipeline finished")


if __name__ == "__main__":
    main()
