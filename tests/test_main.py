import pytest

from main import _validate_selected_stories


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


def test_editorial_guard_requires_exactly_five_stories():
    with pytest.raises(RuntimeError, match="exactly 5"):
        _validate_selected_stories(valid_top5()[:4])


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
    with pytest.raises(RuntimeError, match="four editorial pillars"):
        _validate_selected_stories(top5)


def test_editorial_guard_rejects_unknown_topic():
    top5 = valid_top5()
    top5[0]["topics"] = ["robotics", "politics"]
    with pytest.raises(RuntimeError, match="unsupported topics"):
        _validate_selected_stories(top5)


def test_editorial_guard_requires_topic_diversity():
    top5 = [story(f"https://example.com/{i}", "robotics") for i in range(5)]
    with pytest.raises(RuntimeError, match="topic diversity is too low"):
        _validate_selected_stories(top5)
