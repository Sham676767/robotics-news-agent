from datetime import datetime, timezone

from app.collector import collect_from_source


def test_collect_from_source_normalizes_html_and_parses_dates(monkeypatch):
    class Response:
        content = b"<rss/>"

        def raise_for_status(self):
            return None

    class Feed:
        bozo = False
        entries = [
            {
                "title": "  Humanoid <b>robot</b>  ",
                "link": " https://example.com/a ",
                "summary": "<p>First&nbsp;fact</p>  second fact",
                "published": "2026-08-30T08:00:00+00:00",
            }
        ]

    monkeypatch.setattr("app.collector.httpx.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("app.collector.feedparser.parse", lambda content: Feed())

    items = collect_from_source({"name": "Test", "url": "https://example.com/feed", "language": "en"})

    assert len(items) == 1
    assert items[0].title == "Humanoid robot"
    assert items[0].summary == "First\u00a0fact second fact"
    assert items[0].published_at == datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)


def test_collect_from_source_skips_entries_without_title_or_link(monkeypatch):
    class Response:
        content = b"<rss/>"

        def raise_for_status(self):
            return None

    class Feed:
        bozo = False
        entries = [
            {"title": "", "link": "https://example.com/1"},
            {"title": "Valid", "link": ""},
            {"title": "Valid", "link": "https://example.com/2"},
        ]

    monkeypatch.setattr("app.collector.httpx.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("app.collector.feedparser.parse", lambda content: Feed())

    items = collect_from_source({"name": "Test", "url": "https://example.com/feed"})
    assert [item.url for item in items] == ["https://example.com/2"]
