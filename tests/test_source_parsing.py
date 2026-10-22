from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.source_config import SourceConfig, load_source_config
from app.source_parsing import enrich_article, parse_date, parse_html_listing, parse_rss
from app.topics import Article

FIXTURES = Path(__file__).parent / "fixtures/collection"


@pytest.mark.parametrize("text", ["22.10.2026 12:00", "22 октября 2026 12:00", "2026-10-22T12:00:00+03:00", "Thu, 22 Oct 2026 09:00:00 GMT"])
def test_source_dates_are_normalized_to_utc(text):
    assert parse_date(text) == datetime(2026, 10, 22, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize("text", ["", "вчера", "только что", "35.99.2026"])
def test_missing_and_relative_dates_are_not_invented(text):
    assert parse_date(text) is None


def test_rss_parses_body_dates_links_and_skips_empty_title():
    source = SourceConfig("test", "Тест", "https://media.example/rss", "rss", "media")
    items = parse_rss((FIXTURES / "feed.xml").read_text(), source, 10)
    assert len(items) == 2
    assert items[0].published_at == datetime(2026, 10, 22, 6, tzinfo=timezone.utc)
    assert items[0].url == "https://media.example/news/1"
    assert "Учебный текст" in items[0].text
    assert items[0].links[0].url == "https://law.example/document/100"
    assert items[1].published_at is None


def test_atom_feed_supported():
    source = SourceConfig("test", "Тест", "https://media.example/feed", "rss", "media")
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><title>Test</title><entry><title>Учебная тема</title><link href="https://media.example/1"/><updated>2026-10-22T10:00:00Z</updated><summary>Учебный текст</summary></entry></feed>'
    items = parse_rss(atom, source, 3)
    assert items[0].published_at == datetime(2026, 10, 22, 10, tzinfo=timezone.utc)


def test_html_listing_uses_selectors_relative_links_and_date():
    source = SourceConfig("test", "Тест", "https://media.example/news/", "html", "media",
                          item_selector=".entry", title_selector=".title", summary_selector=".summary")
    items = parse_html_listing((FIXTURES / "listing.html").read_text(), source, 10)
    assert len(items) == 1
    assert items[0].url == "https://media.example/news/1"
    assert items[0].text == "Описание учебного спора."
    assert items[0].published_at == datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def test_article_metadata_and_primary_links_are_kept_navigation_removed():
    source = SourceConfig("test", "Тест", "https://media.example/", "rss", "media")
    article = Article("test", "Тест", "media", "https://media.example/1", "Учебный договор", "", None)
    html = '<meta property="article:published_time" content="2026-10-22T09:00:00Z"><article><nav>Реклама</nav><p>Учебный спор по договору.</p><a href="https://law.example/document/100">99999-ФЗ</a></article>'
    item = enrich_article(article, html, source, article.url)
    assert item.published_at == datetime(2026, 10, 22, 9, tzinfo=timezone.utc)
    assert "Реклама" not in item.text
    assert item.links[0].url == "https://law.example/document/100"


def test_non_feed_response_is_an_error():
    with pytest.raises(ValueError, match="not an RSS"):
        parse_rss("<html>Blocked</html>", SourceConfig("s", "S", "https://x.example/", "rss", "media"), 10)


def test_default_sources_config_has_all_requested_categories():
    config = load_source_config(Path("sources.yaml"))
    assert config.freshness_days == 30
    assert config.topics_per_video == 1
    assert {"official-publication", "state-duma", "constitutional-court", "supreme-court"} <= {item.id for item in config.sources}
    assert {"html", "rss"} == {item.format for item in config.sources}
    assert sum(source.kind == "media" for source in config.sources) >= 2


@pytest.mark.parametrize("change", ["collection: []", "sources: []", "primary_hosts: [https://evil.example]", "collection: {freshness_days: false}"])
def test_config_rejects_invalid_shapes(tmp_path, change):
    path = tmp_path / "bad.yaml"
    original = Path("sources.yaml").read_text()
    import yaml
    data = yaml.safe_load(original)
    data.update(yaml.safe_load(change))
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        load_source_config(path)


def test_explicit_feed_url_rules_preserve_working_https_slash_url():
    source = SourceConfig("test", "Тест", "https://media.example/rss", "rss", "media", article_https=True, article_trailing_slash=True)
    feed = '<rss version="2.0"><channel><title>Тест</title><item><title>Учебная тема</title><link>http://media.example/news/123</link></item></channel></rss>'
    assert parse_rss(feed, source, 1)[0].url == "https://media.example/news/123/"
