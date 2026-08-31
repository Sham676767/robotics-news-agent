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


def test_drone_with_humanoid_is_allowed():
    item = NewsItem(
        source="Test",
        title="Humanoid robot uses a drone for warehouse inspection",
        url="https://example.com/9",
    )
    assert is_relevant(item)
    assert "humanoid" in classify(item)


def test_autonomous_truck_robotics_story_is_rejected_without_specific_pillar():
    item = NewsItem(
        source="Test",
        title="Autonomous truck company announces new robotics research",
        url="https://example.com/10",
    )
    assert not is_relevant(item)


def test_reinforcement_learning_alone_is_rejected():
    item = NewsItem(
        source="Test",
        title="Researchers improve reinforcement learning algorithm",
        url="https://example.com/11",
    )
    assert not is_relevant(item)


def test_filter_keeps_only_relevant_items():
    items = [
        NewsItem(source="Test", title="Humanoid robot enters factory", url="https://example.com/12"),
        NewsItem(source="Test", title="New smartphone announced", url="https://example.com/13"),
        NewsItem(source="Test", title="Drone delivery service expands", url="https://example.com/14"),
        NewsItem(source="Test", title="Powered exoskeleton helps workers lift loads", url="https://example.com/15"),
    ]
    result = filter_relevant(items)
    assert len(result) == 2
    assert {item.url for item in result} == {
        "https://example.com/12",
        "https://example.com/15",
    }


def test_ai_research_about_robotics_without_robot_pillar_is_still_allowed():
    item = NewsItem(
        source="Test",
        title="Robotics lab publishes new robot manipulation benchmark",
        summary="The paper evaluates manipulation policies on industrial robots.",
        url="https://example.com/16",
    )
    assert is_relevant(item)
    assert "robotics" in classify(item)
