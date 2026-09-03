from app import daily_selection
from app.models import NewsItem


def _candidate(item_id, title, source, topics):
    return {
        "id": item_id,
        "title": title,
        "source": source,
        "url": f"https://example.com/{item_id}",
        "published_at": "2026-08-31T08:00:00+00:00",
        "summary": title,
        "topics": topics,
    }


def test_semantic_duplicate_detects_social_expressiveness_mistakes_and_trust_story():
    robohub = NewsItem(
        source="Robohub",
        title="When expressive humanoid robots are awkward, people become wary",
        url="https://example.com/robohub",
        summary="People become more suspicious when an expressive conversation robot makes errors.",
    )
    techxplore = NewsItem(
        source="Tech Xplore Robotics",
        title="A humanoid robot's social expressiveness may backfire when it makes mistakes",
        url="https://example.com/techxplore",
        summary="Researchers tested whether socially expressive behaviors affect trust in a robot.",
    )

    assert daily_selection._near_duplicate(robohub, techxplore)


def test_partnership_platform_and_market_material_is_promotional_without_concrete_event():
    item = NewsItem(
        source="The Robot Report",
        title="HowToRobot and Robotics Australia Group partner on platform to encourage robot adoption",
        url="https://example.com/partner",
        summary="The initiative helps businesses identify automation opportunities and connect with suppliers.",
    )

    assert daily_selection._is_promotional(item)


def test_conference_invitation_is_promotional_without_a_concrete_event():
    item = NewsItem(
        source="The Robot Report",
        title="Learn why food is physical AI’s hardest problem at RoboBusiness",
        url="https://example.com/robobusiness",
        summary="The founder and CEO of Chef Robotics will explore a demanding benchmark.",
    )

    assert daily_selection._is_promotional(item)


def test_filter_editorial_drops_google_news_when_five_direct_materials_exist():
    items = [
        NewsItem(source=f"Direct {index}", title=f"Robot event {index}", url=f"https://example.com/direct-{index}")
        for index in range(5)
    ]
    items.append(
        NewsItem(
            source="Google News Robotics Research",
            title="Video: 3D-printed Berkeley Humanoid Lite - Interesting Engineering",
            url="https://example.com/aggregated",
        )
    )

    filtered = daily_selection._filter_editorial(items)

    assert len(filtered) == 5
    assert all(not item.source.startswith("Google News") for item in filtered)


def test_top5_does_not_force_stale_topic_coverage_over_fresh_event(monkeypatch):
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    candidates = [
        {**_candidate(1, "Old robot dog overview", "A", ("robot_dog", "robotics")), "published_at": (now - __import__("datetime").timedelta(days=6)).isoformat()},
        {**_candidate(2, "Fresh robotics deployment", "B", ("robotics",)), "published_at": (now - __import__("datetime").timedelta(hours=18)).isoformat()},
        {**_candidate(3, "Old humanoid research", "C", ("humanoid", "robotics")), "published_at": (now - __import__("datetime").timedelta(days=5)).isoformat()},
        {**_candidate(4, "Old exoskeleton update", "D", ("exoskeleton", "robotics")), "published_at": (now - __import__("datetime").timedelta(days=5)).isoformat()},
        {**_candidate(5, "Older robotics event", "E", ("robotics",)), "published_at": (now - __import__("datetime").timedelta(days=4)).isoformat()},
    ]
    monkeypatch.setattr(daily_selection, "build_candidates", lambda items=None: candidates)
    monkeypatch.setattr(
        daily_selection,
        "rank_with_deepseek",
        lambda items, limit: [
            {"id": 2, "score": 95},
            {"id": 1, "score": 30},
            {"id": 3, "score": 29},
            {"id": 4, "score": 28},
            {"id": 5, "score": 27},
        ],
    )

    result = daily_selection.select_top5(news=[])

    assert result[0]["id"] == 2


def test_top5_prefers_specific_topic_coverage(monkeypatch):
    candidates = [
        _candidate(1, "Humanoid robot enters factory", "A", ("humanoid", "robotics")),
        _candidate(2, "Robot dog gets new navigation system", "B", ("robot_dog", "robotics")),
        _candidate(3, "Powered exoskeleton starts pilot", "C", ("exoskeleton", "robotics")),
        _candidate(4, "Another humanoid robot demo", "D", ("humanoid", "robotics")),
        _candidate(5, "Humanoid robot arm research", "E", ("humanoid", "robotics")),
    ]

    monkeypatch.setattr(daily_selection, "build_candidates", lambda items=None: candidates)
    monkeypatch.setattr(
        daily_selection,
        "rank_with_deepseek",
        lambda items, limit: [
            {"id": 1, "score": 10},
            {"id": 4, "score": 9},
            {"id": 5, "score": 8},
            {"id": 2, "score": 7},
            {"id": 3, "score": 6},
        ],
    )

    result = daily_selection.select_top5(news=[])
    ids = [item["id"] for item in result]

    assert len(result) == 5
    assert {1, 2, 3}.issubset(set(ids))
    assert len(ids) == len(set(ids))


def test_top5_can_use_multitopic_story_to_cover_two_pillars(monkeypatch):
    candidates = [
        _candidate(1, "Humanoid exoskeleton platform", "A", ("humanoid", "exoskeleton", "robotics")),
        _candidate(2, "Robot dog patrol system", "B", ("robot_dog", "robotics")),
        _candidate(3, "General factory robotics", "C", ("robotics",)),
        _candidate(4, "Humanoid assembly robot", "D", ("humanoid", "robotics")),
        _candidate(5, "Exoskeleton update", "E", ("exoskeleton", "robotics")),
    ]

    monkeypatch.setattr(daily_selection, "build_candidates", lambda items=None: candidates)
    monkeypatch.setattr(
        daily_selection,
        "rank_with_deepseek",
        lambda items, limit: [{"id": i, "score": 10 - i} for i in range(1, 6)],
    )

    result = daily_selection.select_top5(news=[])
    ids = {item["id"] for item in result}

    assert 1 in ids
    assert 2 in ids
    assert len(result) == 5
