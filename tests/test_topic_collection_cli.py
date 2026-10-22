import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from app.cli import main
from app.config import Settings
from app.openrouter_client import OpenRouterError
from app.source_config import load_source_config
from app.source_http import FetchedPage, SourceFetchError
from app.topic_collector import collect_topics
from app.topic_history import TopicHistory

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
KEY = Settings(openrouter_api_key="test-only-key")


@pytest.fixture
def collection_setup(tmp_path, monkeypatch):
    config_path = tmp_path / "sources.yaml"
    data = {
        "collection": {"freshness_days": 30, "history_path": str(tmp_path / "history.sqlite3"), "output_path": str(tmp_path / "result.json")},
        "primary_hosts": ["law.example"],
        "sources": [{"id": "test", "name": "Тест", "url": "https://media.example/rss", "format": "rss", "kind": "media"}],
    }
    config_path.write_text(yaml.safe_dump(data))
    config = load_source_config(config_path)
    feed = (Path(__file__).parent / "fixtures/collection/feed.xml").read_text()
    pages = {
        "https://media.example/rss": FetchedPage("https://media.example/rss", feed, "application/xml"),
        "https://media.example/news/1": FetchedPage("https://media.example/news/1", '<article><p>Учебный договор: спор бизнеса и взыскание задолженности. Синтетический реквизит 99999-ФЗ.</p><a href="https://law.example/document/100">Учебный первоисточник</a></article>', "text/html"),
        "https://media.example/news/2": FetchedPage("https://media.example/news/2", "<article>Тема без даты</article>", "text/html"),
        "https://law.example/document/100": FetchedPage("https://law.example/document/100", "<h1>Учебный документ 99999-ФЗ</h1>", "text/html"),
    }
    def fetch(self, url):
        if url not in pages:
            raise SourceFetchError("Unavailable test source")
        return pages[url]
    monkeypatch.setattr("app.source_http.SourceFetcher.fetch", fetch)
    def compare(messages, **kwargs):
        ids = [card["id"] for card in json.loads(messages[-1]["content"])]
        return {"groups": [[key] for key in ids]}
    monkeypatch.setattr("app.topic_dedup.request_json", compare)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-key")
    return config_path, config, pages


def test_pipeline_selection_then_explicit_mark_then_exclusion(collection_setup):
    _, config, _ = collection_setup
    first = collect_topics(config, KEY, now=NOW)
    assert len(first["selected_topics"]) == 1
    topic_id = first["selected_topics"][0]["id"]
    assert first["selected_topics"][0]["primary_references"][0]["citation"] == "99999-ФЗ"
    with TopicHistory(config.history_path) as history:
        assert not history.used_topics()
    second = collect_topics(config, KEY, now=NOW)
    assert second["selected_topics"][0]["id"] == topic_id
    with TopicHistory(config.history_path) as history:
        history.mark_used([topic_id])
    third = collect_topics(config, KEY, now=NOW)
    assert third["selected_topics"] == []
    assert third["used_topics_excluded"] == 1


def test_partial_source_failure_keeps_available_topics(collection_setup):
    _, config, _ = collection_setup
    broken = replace(config.sources[0], id="broken", url="https://media.example/broken")
    report = collect_topics(replace(config, sources=(*config.sources, broken)), KEY, now=NOW)
    assert report["status"] == "partial"
    assert len(report["selected_topics"]) == 1
    assert report["source_errors"][0]["source"] == "broken"


def test_all_sources_unavailable_writes_diagnostics(collection_setup):
    _, config, pages = collection_setup
    pages.clear()
    with pytest.raises(ValueError, match="No articles collected"):
        collect_topics(config, KEY, now=NOW)
    assert json.loads(config.output_path.read_text())["status"] == "unavailable"


def test_missing_key_fails_before_collecting_or_creating_history(collection_setup):
    _, config, _ = collection_setup
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        collect_topics(config, Settings(), now=NOW)
    assert not config.history_path.exists()


def test_model_failure_cannot_leave_previous_selection_as_current(collection_setup, monkeypatch):
    _, config, pages = collection_setup
    # Add a second distinct fresh topic so semantic comparison must occur.
    pages["https://media.example/rss"] = replace(pages["https://media.example/rss"], text=pages["https://media.example/rss"].text.replace('<title>Элемент без даты</title>', '<title>Другое событие</title><pubDate>Thu, 22 Oct 2026 09:00:00 +0300</pubDate>'))
    config.output_path.write_text('{"status":"ok","selected_topics":["old"]}')
    monkeypatch.setattr("app.topic_dedup.request_json", Mock(side_effect=OpenRouterError("test failure")))
    with pytest.raises(OpenRouterError):
        collect_topics(config, KEY, now=NOW)
    assert json.loads(config.output_path.read_text())["selected_topics"] == []
    with TopicHistory(config.history_path) as history:
        assert history.used_topics() == []
        assert history.connection.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 0


def test_cli_collect_and_mark_used(collection_setup, capsys):
    path, config, _ = collection_setup
    assert main(["collect", "--sources", str(path)]) == 0
    report = json.loads(config.output_path.read_text())
    topic_id = report["selected_topics"][0]["id"]
    assert main(["mark-used", topic_id, "--sources", str(path)]) == 0
    with TopicHistory(config.history_path) as history:
        assert history.used_topics()[0].id == topic_id
    assert main(["collect", "--sources", str(path)]) == 3


def test_cli_count_and_window_overrides(collection_setup):
    path, config, _ = collection_setup
    assert main(["collect", "--sources", str(path), "--count", "2", "--max-age-days", "40"]) == 3
    report = json.loads(config.output_path.read_text())
    assert report["topics_per_video"] == 2 and report["freshness_days"] == 40
    assert len(report["selected_topics"]) == 1  # no invented filler


@pytest.mark.parametrize("flag", ["--count", "--max-age-days"])
def test_cli_rejects_nonpositive_settings(collection_setup, flag):
    path, _, _ = collection_setup
    assert main(["collect", "--sources", str(path), flag, "0"]) == 2
