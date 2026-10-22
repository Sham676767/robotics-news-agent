import json
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.topic_dedup import local_deduplicate, semantic_deduplicate
from app.topic_urls import canonical_url
from app.topics import Article


def article(url, title="Учебный договор", text="Учебный текст " * 10):
    return Article("test", "Тестовый источник", "media", url, title, text, datetime(2026, 10, 22, tzinfo=timezone.utc))


@pytest.mark.parametrize(("url", "expected"), [
    ("https://EXAMPLE.com:443/news/1/?utm_source=x&id=2#part", "https://example.com/news/1/?id=2"),
    ("https://example.com/doc?id=1&ysclid=abc", "https://example.com/doc?id=1"),
])
def test_url_normalization_removes_tracking_but_keeps_document_id(url, expected):
    assert canonical_url(url) == expected


def test_different_document_query_parameters_remain_distinct():
    assert canonical_url("https://x.example/doc?id=1") != canonical_url("https://x.example/doc?id=2")


def test_same_url_and_exact_syndication_merge_without_losing_sources():
    items = [article("https://x.example/1"), article("https://x.example/1?utm_source=feed"), article("https://y.example/2")]
    topics = local_deduplicate(items)
    assert len(topics) == 1
    assert len(topics[0].articles) == 3


def test_same_reference_alone_does_not_merge_local_topics():
    items = [article("https://x.example/1", "Учебное изменение", "Учебный документ 99999-ФЗ"),
             article("https://x.example/2", "Другое учебное изменение", "Учебный документ 99999-ФЗ")]
    assert len(local_deduplicate(items)) == 2


def test_semantic_merge_keeps_all_source_urls():
    topics = local_deduplicate([article("https://x.example/1", "Тема первая"), article("https://x.example/2", "Перефразировка")])
    requester = Mock(return_value={"groups": [["new:0", "new:1"]]})
    result, excluded = semantic_deduplicate(topics, [], Settings(), requester=requester)
    assert len(result) == 1 and excluded == 0
    assert {a.url for a in result[0].articles} == {"https://x.example/1", "https://x.example/2"}


@pytest.mark.parametrize("result", [{"groups": [["invented"]]}, {"groups": [["new:0"], ["new:0"]]}, {"groups": []}, {"groups": "wrong"}, {"groups": [[]]}])
def test_model_cannot_invent_drop_or_repeat_ids(result):
    topics = local_deduplicate([article("https://x.example/1", "Первая"), article("https://x.example/2", "Вторая")])
    with pytest.raises(ValueError):
        semantic_deduplicate(topics, [], Settings(), requester=Mock(return_value=result))


def test_semantic_history_excludes_rephrased_used_topic():
    topics = local_deduplicate([article("https://x.example/new")])
    used = local_deduplicate([article("https://x.example/old", "Перефразированная тема")])
    result, excluded = semantic_deduplicate(topics, used, Settings(), requester=Mock(return_value={"groups": [["new:0", "used:0"]]}))
    assert result == [] and excluded == 1


def test_every_history_chunk_and_cross_candidate_chunk_is_compared():
    topics = local_deduplicate([article(f"https://x.example/{i}", f"Тема {i}", f"Различающийся текст {i}") for i in range(5)])
    used = local_deduplicate([article(f"https://old.example/{i}", f"Архив {i}", f"Исторический текст {i}") for i in range(5)])
    calls = []
    def request(messages, **kwargs):
        ids = [item["id"] for item in json.loads(messages[-1]["content"])]
        calls.append(set(ids))
        return {"groups": [[item] for item in ids]}
    result, _ = semantic_deduplicate(topics, used, Settings(), batch_size=2, requester=request)
    assert len(result) == 5
    for left in range(5):
        for right in range(5):
            assert any({f"new:{left}", f"used:{right}"} <= call for call in calls)
        for right in range(left + 1, 5):
            assert any({f"new:{left}", f"new:{right}"} <= call for call in calls)


def test_alias_count_cannot_change_stable_topic_identifier():
    one = local_deduplicate([article('https://x.example/1')])[0]
    two = local_deduplicate([article('https://x.example/1'), article('https://x.example/1?utm_source=feed')])[0]
    assert one.id == two.id


def test_significant_date_and_from_query_parameters_are_preserved():
    assert canonical_url('https://x.example/search?from=2026-10-01&date=2026-10-22') == 'https://x.example/search?date=2026-10-22&from=2026-10-01'
