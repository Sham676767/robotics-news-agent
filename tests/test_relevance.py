from app.models import NewsItem
from app.relevance import classify, filter_relevant, is_relevant


def test_humanoid_is_relevant():
    item = NewsItem(source="Test", title="Startup unveils a new humanoid robot", url="https://example.com/1")
    assert is_relevant(item)
    assert "humanoid" in classify(item)


def test_robot_dog_is_relevant():
    item = NewsItem(source="Test", title="New robot dog learns to climb stairs", url="https://example.com/2")
    assert is_relevant(item)
    assert "robot_dog" in classify(item)


def test_exoskeleton_is_relevant():
    item = NewsItem(source="Test", title="Powered exoskeleton enters a rehabilitation pilot", url="https://example.com/3")
    assert is_relevant(item)
    assert "exoskeleton" in classify(item)


def test_general_robotics_is_relevant():
    item = NewsItem(source="Test", title="New robot manipulation system improves factory robotics", url="https://example.com/4")
    assert is_relevant(item)
    assert "robotics" in classify(item)


def test_unrelated_ai_news_is_rejected():
    item = NewsItem(source="Test", title="Company releases a new text AI model", url="https://example.com/5")
    assert not is_relevant(item)


def test_drone_news_is_rejected():
    item = NewsItem(source="Test", title="New drone platform gets a major contract", url="https://example.com/6")
    assert not is_relevant(item)


def test_robotaxi_news_is_rejected():
    item = NewsItem(source="Test", title="Robotaxi fleet expands to another city", url="https://example.com/7")
    assert not is_relevant(item)


def test_autonomous_vehicle_with_humanoid_is_allowed():
    item = NewsItem(
        source="Test",
        title="Humanoid robot tested alongside autonomous vehicles",
        url="https://example.com/8",
    )
    assert is_relevant(item)
    assert "humanoid" in classify(item)


def test_filter_keeps_only_relevant_items():
    items = [
        NewsItem(source="Test", title="Humanoid robot enters factory", url="https://example.com/9"),
        NewsItem(source="Test", title="New smartphone announced", url="https://example.com/10"),
        NewsItem(source="Test", title="Drone delivery service expands", url="https://example.com/11"),
    ]
    result = filter_relevant(items)
    assert len(result) == 1
    assert result[0].url.endswith("/9")
