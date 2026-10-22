from dataclasses import replace
from pathlib import Path
from types import MethodType
from unittest.mock import Mock

import httpx
import pytest

from app.source_config import load_source_config
from app.source_http import SourceFetcher, SourceFetchError

# Captured before the autouse network block; used only with MockTransport.
SEND = httpx.Client.send


def fetcher(monkeypatch, handler, **changes):
    config = replace(load_source_config(Path("sources.yaml")), fetch_attempts=2, **changes)
    item = SourceFetcher(config)
    item.client.close()
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True,
                          event_hooks={"request": [item._check_destination]})
    monkeypatch.setattr(client, "send", MethodType(SEND, client))
    monkeypatch.setattr("app.source_http.time.sleep", Mock())
    item.client = client
    return item


def test_source_download_retries_transient_failures_and_caches(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, text="<rss/>")
    with fetcher(monkeypatch, handler) as item:
        assert item.fetch("https://pravo.ru/rss/").text == "<rss/>"
        item.fetch("https://pravo.ru/rss/")
    assert len(calls) == 2


def test_permanent_source_errors_are_not_retried(monkeypatch):
    handler = Mock(return_value=httpx.Response(403))
    with fetcher(monkeypatch, handler) as item:
        with pytest.raises(SourceFetchError, match="403"):
            item.fetch("https://pravo.ru/rss/")
    assert handler.call_count == 1


def test_redirect_cannot_fetch_unconfigured_destination(monkeypatch):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    with fetcher(monkeypatch, handler) as item:
        with pytest.raises(SourceFetchError, match="outside configured"):
            item.fetch("https://pravo.ru/rss/")
    assert calls == ["https://pravo.ru/rss/"]


def test_oversized_source_response_fails(monkeypatch):
    with fetcher(monkeypatch, lambda request: httpx.Response(200, text="too much text"), max_response_bytes=3) as item:
        with pytest.raises(SourceFetchError, match="exceeds"):
            item.fetch("https://pravo.ru/rss/")


def test_xml_declared_encoding_preserved_without_charset_header(monkeypatch):
    content = '<?xml version="1.0" encoding="windows-1251"?><rss><title>Учебный текст</title></rss>'.encode("cp1251")
    with fetcher(monkeypatch, lambda request: httpx.Response(200, content=content)) as item:
        assert "Учебный текст" in item.fetch("https://pravo.ru/rss/").text


def test_pdf_content_type_without_pdf_body_is_not_evidence(monkeypatch):
    with fetcher(monkeypatch, lambda request: httpx.Response(200, content=b'Blocked', headers={'content-type': 'application/pdf'})) as item:
        with pytest.raises(SourceFetchError, match='Invalid PDF'):
            item.fetch('https://pravo.gov.ru/document/100')
