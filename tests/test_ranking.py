from datetime import datetime, timedelta, timezone

from app.models import NewsItem
from app.ranking import rank, score


def test_humanoid_news_scores_above_generic_robot_news():
    now = datetime.now(timezone.utc)
    humanoid = NewsItem(
        source="IEEE Spectrum Robotics",
        title="Company unveils new humanoid robot for commercial deployment",
        published_at=now,
    )
    generic = NewsItem(
        source="Unknown",
        title="Robotics industry event announced",
        published_at=now,
    )

    assert score(humanoid, now) > score(generic, now)


def test_fresh_news_scores_above_old_news_when_otherwise_equal():
    now = datetime.now(timezone.utc)
    fresh = NewsItem(source="Unknown", title="Humanoid robot update", published_at=now)
    old = NewsItem(
        source="Unknown",
        title="Humanoid robot update",
        published_at=now - timedelta(days=14),
    )

    assert score(fresh, now) > score(old, now)


def test_rank_returns_requested_number():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(source="Unknown", title=f"Humanoid robot story {i}", published_at=now)
        for i in range(10)
    ]

    result = rank(items, limit=5, now=now)
    assert len(result) == 5
