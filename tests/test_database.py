from app.database import connect, count_items, save_items
from app.models import NewsItem


def test_save_and_deduplicate(tmp_path):
    db = connect(tmp_path / "news.db")
    item = NewsItem(source="Test", title="New humanoid robot", url="https://example.com/1")
    same_story = NewsItem(source="Another feed", title="New humanoid robot", url="https://example.com/2")

    inserted, duplicates = save_items(db, [item, same_story])

    assert inserted == 1
    assert duplicates == 1
    assert count_items(db) == 1
