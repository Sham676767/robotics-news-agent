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


def test_unrelated_ai_news_is_rejected():
    item = NewsItem(source="Test", title="Company releases a new text AI model", url="https://example.com/3")
    assert not is_relevant(item)


def test_filter_keeps_only_relevant_items():
    items = [
        NewsItem(source="Test", title="Humanoid robot enters factory", url="https://example.com/4"),
        NewsItem(source="Test", title="New smartphone announced", url="https://example.com/5"),
    ]
    result = filter_relevant(items)
    assert len(result) == 1
    assert result[0].url.endswith("/4")
