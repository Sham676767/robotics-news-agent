from datetime import datetime, timedelta, timezone

from app.models import NewsItem
from app.ranking import rank, score


def test_humanoid_news_scores_above_generic_robot_news():
    now = datetime.now(timezone.utc)
    humanoid = NewsItem(
        source="IEEE Spectrum Robotics",
        title="Company unveils new humanoid robot for commercial deployment",
        url="https://example.com/humanoid",
        published_at=now,
    )
    generic = NewsItem(
        source="Unknown",
        title="Robotics industry event announced",
        url="https://example.com/generic",
        published_at=now,
    )

    assert score(humanoid, now) > score(generic, now)


def test_fresh_news_scores_above_old_news_when_otherwise_equal():
    now = datetime.now(timezone.utc)
    fresh = NewsItem(
        source="Unknown",
        title="Humanoid robot update",
        url="https://example.com/fresh",
        published_at=now,
    )
    old = NewsItem(
        source="Unknown",
        title="Humanoid robot update",
        url="https://example.com/old",
        published_at=now - timedelta(days=14),
    )

    assert score(fresh, now) > score(old, now)


def test_fresh_concrete_event_beats_promotional_market_discussion():
    now = datetime.now(timezone.utc)
    concrete = NewsItem(
        source="Direct Publisher",
        title="Robot dog demonstrated in warehouse deployment pilot",
        url="https://example.com/concrete",
        published_at=now - timedelta(hours=18),
        summary="The company demonstrated the quadruped in a concrete warehouse pilot.",
        topics=["robot_dog"],
    )
    promo = NewsItem(
        source="The Robot Report",
        title="NexCOBOT discusses physical AI market hurdles and acceleration",
        url="https://example.com/promo",
        published_at=now - timedelta(hours=6),
        summary="The company discusses market outlook and industry trends.",
        topics=["robotics"],
    )

    assert score(concrete, now) > score(promo, now)


def test_rank_returns_requested_number():
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            source="Unknown",
            title=f"Humanoid robot story {i}",
            url=f"https://example.com/{i}",
            published_at=now,
        )
        for i in range(10)
    ]

    result = rank(items, limit=5, now=now)
    assert len(result) == 5
