from app import daily_selection


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
