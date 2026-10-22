from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.primary_evidence import find_primary_references, is_document_url
from app.source_http import FetchedPage, SourceFetchError
from app.topic_dedup import local_deduplicate
from app.topic_history import TopicHistory
from app.topic_selection import select_topics
from app.topics import Article, PrimaryReference, SourceLink

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def topic(url="https://media.example/1", title="Учебный спор бизнеса по договору", days=1):
    item = Article("test", "Тест", "media", url, title, "Синтетический материал 99999-ФЗ: договор, контрагент, взыскание задолженности.", NOW - timedelta(days=days), (SourceLink("https://law.example/document/100"),))
    return replace(local_deduplicate([item])[0], references=(PrimaryReference("law", "99999-ФЗ", "https://law.example/document/100", "Синтетический реквизит 99999-ФЗ", True),))


def test_collection_does_not_mean_used_and_confirmation_survives_reopening(tmp_path):
    path = tmp_path / "history.sqlite3"
    item = topic()
    with TopicHistory(path) as history:
        history.save_selected([item])
        assert history.used_topics() == []
        assert history.mark_used([item.id]) == 1
        assert history.mark_used([item.id]) == 0
    with TopicHistory(path) as history:
        assert history.used_topics() == [item]
        history.save_selected([replace(item, title="Изменённый текст")])
        assert history.used_topics()[0].title == item.title


def test_unknown_id_does_not_partially_mark_others(tmp_path):
    item = topic()
    with TopicHistory(tmp_path / "history.sqlite3") as history:
        history.save_selected([item])
        with pytest.raises(ValueError, match="Unknown"):
            history.mark_used([item.id, "nonexistent"])
        assert history.used_topics() == []


def test_selection_is_one_by_default_and_count_configurable():
    topics = [topic(), topic("https://media.example/2", days=2)]
    assert len(select_topics(topics, 1, 30, NOW)) == 1
    assert len(select_topics(topics, 2, 30, NOW)) == 2
    assert select_topics(topics, 1, 30, NOW)[0].topic.id == topics[0].id


@pytest.mark.parametrize("case", ["stale", "undated", "future", "missing_primary", "irrelevant"])
def test_selection_requires_freshness_usefulness_and_primary(case):
    item = topic()
    if case in {"stale", "undated", "future"}:
        date = {"stale": NOW - timedelta(days=31), "undated": None, "future": NOW + timedelta(days=1)}[case]
        item = replace(item, articles=(replace(item.articles[0], published_at=date),))
    elif case == "missing_primary":
        item = replace(item, references=())
    else:
        item = replace(item, title="Официальная встреча", articles=(replace(item.articles[0], title="Официальная встреча", text="Состоялось торжественное мероприятие."),))
    assert select_topics([item], 1, 30, NOW) == []


def test_30_day_window_keeps_a_topic_older_than_seven_days():
    assert len(select_topics([topic(days=20)], 1, 30, NOW)) == 1
    assert select_topics([topic(days=20)], 1, 7, NOW) == []


def test_more_recent_low_value_news_cannot_replace_practical_topic():
    items = [topic(days=3), topic("https://media.example/2", "Торжественная встреча", 0)]
    items[1] = replace(items[1], articles=(replace(items[1].articles[0], text="Состоялось торжественное мероприятие."),))
    assert select_topics(items, 1, 30, NOW)[0].topic.id == items[0].id


class Fetcher:
    def __init__(self, page): self.page = page
    def fetch(self, url):
        if isinstance(self.page, Exception): raise self.page
        return self.page


def test_primary_reference_requires_direct_trusted_available_document():
    item = topic().articles[0]
    page = FetchedPage("https://law.example/document/100", "<h1>Учебный документ 99999-ФЗ</h1>", "text/html")
    refs = find_primary_references((item,), ("law.example",), Fetcher(page))
    assert refs[0].citation == "99999-ФЗ"
    assert refs[0].availability_verified
    assert refs[0].citation in refs[0].excerpt
    assert find_primary_references((item,), ("other.example",), Fetcher(page)) == ()
    assert find_primary_references((item,), ("law.example",), Fetcher(SourceFetchError("unavailable"))) == ()


def test_primary_html_must_expose_matching_identifier():
    page = FetchedPage("https://law.example/document/100", "<p>Несвязанный документ</p>", "text/html")
    assert find_primary_references(topic().articles, ("law.example",), Fetcher(page)) == ()


def test_homepage_is_not_primary_document():
    assert not is_document_url("https://law.example/")
    assert not is_document_url("https://law.example/news/100")
