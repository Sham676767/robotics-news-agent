from unittest.mock import Mock

import httpx
import pytest

from app.config import Settings
from app.openrouter_client import OpenRouterError, parse_json_object, request_json

MESSAGES = [{"role": "user", "content": "Технический тест JSON, без правовых утверждений."}]


def response(status=200, *, content='{"title": "Тест"}', headers=None):
    return httpx.Response(status, headers=headers, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def settings():
    return Settings(openrouter_api_key="test-only-key", retry_base_seconds=0, retry_max_seconds=0)


@pytest.mark.parametrize("text", ['{"value": 1}', '```json\n{"value": 1}\n```', 'answer: {"value": 1} done'])
def test_parses_json_object_formats(text):
    assert parse_json_object(text) == {"value": 1}


@pytest.mark.parametrize("text", ["safe", "[]", "null", '{"broken":}', "42"])
def test_rejects_non_objects_and_invalid_json(text):
    with pytest.raises(ValueError):
        parse_json_object(text)


def test_request_uses_configured_schema_models_and_timeout(monkeypatch, settings):
    settings = Settings(openrouter_api_key="test-only-key", openrouter_model="test/primary", openrouter_fallback_models=("test/primary", "test/backup"))
    post = Mock(return_value=response())
    monkeypatch.setattr(httpx, "post", post)
    schema = {"type": "object"}
    assert request_json(MESSAGES, settings=settings, schema=schema) == {"title": "Тест"}
    payload = post.call_args.kwargs["json"]
    assert payload["models"] == ["test/primary", "test/backup"]
    assert payload["response_format"]["json_schema"]["schema"] == schema
    assert post.call_args.kwargs["timeout"] == settings.openrouter_timeout
    assert post.call_args.kwargs["headers"]["X-Title"] == "Legal Reels Agent"


@pytest.mark.parametrize("status", [408, 409, 429, 500, 502, 503, 504])
def test_retries_transient_status_then_succeeds(monkeypatch, settings, status):
    post = Mock(side_effect=[response(status), response()])
    sleep = Mock()
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.openrouter_client.time.sleep", sleep)
    assert request_json(MESSAGES, settings=settings) == {"title": "Тест"}
    assert post.call_count == 2
    sleep.assert_called_once_with(0)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_does_not_retry_permanent_errors(monkeypatch, settings, status):
    post = Mock(return_value=response(status))
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(OpenRouterError, match=f"HTTP {status}"):
        request_json(MESSAGES, settings=settings)
    assert post.call_count == 1


def test_retries_transport_errors_without_leaking_secrets(monkeypatch, settings, caplog):
    post = Mock(side_effect=[httpx.ConnectTimeout("test-only-key"), response()])
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.openrouter_client.time.sleep", Mock())
    request_json(MESSAGES, settings=settings)
    assert post.call_count == 2
    assert "test-only-key" not in caplog.text


def test_retry_after_is_bounded(monkeypatch):
    settings = Settings(openrouter_api_key="test-only-key", retry_base_seconds=2, retry_max_seconds=5)
    post = Mock(side_effect=[response(429, headers={"Retry-After": "999"}), response()])
    sleep = Mock()
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.openrouter_client.time.sleep", sleep)
    request_json(MESSAGES, settings=settings)
    sleep.assert_called_once_with(5)


@pytest.mark.parametrize("retry_after", ["not-a-delay", "nan", "-10"])
def test_invalid_retry_after_cannot_cause_negative_sleep(monkeypatch, settings, retry_after):
    post = Mock(side_effect=[response(429, headers={"Retry-After": retry_after}), response()])
    sleep = Mock()
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.openrouter_client.time.sleep", sleep)
    request_json(MESSAGES, settings=settings)
    sleep.assert_called_once_with(0)


def test_exhaustion_is_bounded_and_hides_response_body(monkeypatch, settings, caplog):
    post = Mock(return_value=httpx.Response(503, text="test-only-key"))
    sleep = Mock()
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.openrouter_client.time.sleep", sleep)
    with pytest.raises(OpenRouterError, match="after 3 attempts") as error:
        request_json(MESSAGES, settings=settings)
    assert post.call_count == 3
    assert sleep.call_count == 2
    assert "test-only-key" not in str(error.value) + caplog.text


@pytest.mark.parametrize("bad", [response(content="invalid"), response(content=""), httpx.Response(200, json={"choices": []}), httpx.Response(200, json=[])])
def test_invalid_provider_content_is_retried(monkeypatch, settings, bad):
    post = Mock(side_effect=[bad, response()])
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.openrouter_client.time.sleep", Mock())
    assert request_json(MESSAGES, settings=settings) == {"title": "Тест"}
    assert post.call_count == 2


def test_missing_api_key_fails_before_network():
    with pytest.raises(OpenRouterError, match="not configured"):
        request_json(MESSAGES, settings=Settings())


def test_missing_messages_fail_before_network(settings):
    with pytest.raises(ValueError, match="message"):
        request_json([], settings=settings)
