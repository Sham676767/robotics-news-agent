import pytest

from main import _validate_selected_stories, _vk_publication_enabled


def story(url, *topics):
    return {"url": url, "topics": list(topics)}


def valid_top5():
    return [
        story("https://example.com/1", "robotics"),
        story("https://example.com/2", "humanoid"),
        story("https://example.com/3", "robot_dog"),
        story("https://example.com/4", "exoskeleton"),
        story("https://example.com/5", "robotics"),
    ]


def test_editorial_guard_accepts_valid_top5():
    _validate_selected_stories(valid_top5())


def test_editorial_guard_accepts_short_fresh_digest():
    _validate_selected_stories(valid_top5()[:4])


def test_editorial_guard_rejects_empty_or_oversize_list():
    with pytest.raises(RuntimeError, match="between 1 and 5"):
        _validate_selected_stories([])
    with pytest.raises(RuntimeError, match="between 1 and 5"):
        _validate_selected_stories(valid_top5() + [story("https://example.com/6", "robotics")])


def test_editorial_guard_rejects_invalid_url():
    top5 = valid_top5()
    top5[0]["url"] = "not-a-url"
    with pytest.raises(RuntimeError, match="invalid source URL"):
        _validate_selected_stories(top5)


def test_editorial_guard_rejects_duplicate_urls():
    top5 = valid_top5()
    top5[1]["url"] = top5[0]["url"]
    with pytest.raises(RuntimeError, match="duplicate source URLs"):
        _validate_selected_stories(top5)


def test_editorial_guard_rejects_non_robotics_topic():
    top5 = valid_top5()
    top5[0]["topics"] = ["politics"]
    with pytest.raises(RuntimeError, match="editorial pillar"):
        _validate_selected_stories(top5)


def test_editorial_guard_rejects_unknown_topic():
    top5 = valid_top5()
    top5[0]["topics"] = ["robotics", "politics"]
    with pytest.raises(RuntimeError, match="unsupported topics"):
        _validate_selected_stories(top5)


def test_editorial_guard_allows_one_reserve_story():
    _validate_selected_stories([
        story("https://example.com/1", "robotics"),
        story("https://example.com/2", "reserve"),
    ])


def test_editorial_guard_rejects_multiple_reserve_stories():
    with pytest.raises(RuntimeError, match="At most one reserve"):
        _validate_selected_stories([
            story("https://example.com/1", "reserve"),
            story("https://example.com/2", "reserve"),
        ])


def test_editorial_guard_allows_single_topic_when_that_is_all_fresh_news():
    _validate_selected_stories([story(f"https://example.com/{i}", "robotics") for i in range(5)])


def test_vk_publication_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("VK_PUBLISH_ENABLED", raising=False)
    assert not _vk_publication_enabled()


def test_vk_publication_requires_explicit_enable(monkeypatch):
    monkeypatch.setenv("VK_PUBLISH_ENABLED", "true")
    assert _vk_publication_enabled()
