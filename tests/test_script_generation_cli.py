import copy
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from app.cli import main
from app.config import Settings
from app.openrouter_client import OpenRouterError, parse_strict_json_object
from app.reel_script import SCRIPT_SCHEMA, parse_script
from app.script_generator import generate_script, load_script_topic, save_script
from app.script_review import review_script
from app.topic_history import TopicHistory
from app.topics import topic_to_dict


def completion(data):
    content = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def settings(tmp_path):
    return Settings(openrouter_api_key="test-only-key", openrouter_model="fixture/configured-model",
                    retry_base_seconds=0, retry_max_seconds=0, drafts_dir=tmp_path / "drafts")


@pytest.fixture
def report_file(tmp_path, script_topic):
    path = tmp_path / "collection.json"
    path.write_text(json.dumps({"status": "ok", "selected_topics": [topic_to_dict(script_topic)]}))
    return path


@pytest.mark.parametrize("bad", [
    '```json\n{}\n```', 'Пояснение: {}', '{} конец', '[]', 'null',
    '{"a":1,"a":2}', '{"a":{"b":1,"b":2}}', '{"a":NaN}',
    '{"a":Infinity}', '{"a":1e999}', '{"broken":}',
])
def test_strict_parser_rejects_wrappers_duplicates_and_invalid_numbers(bad):
    with pytest.raises(ValueError):
        parse_strict_json_object(bad)


def test_generation_uses_model_schema_and_untrusted_source_data(monkeypatch, settings, script_topic, script_data):
    post = Mock(return_value=completion(script_data))
    monkeypatch.setattr(httpx, "post", post)
    result = generate_script(script_topic, settings)
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == settings.openrouter_model
    assert payload["response_format"]["json_schema"] == {
        "name": "reel_script", "strict": True, "schema": SCRIPT_SCHEMA,
    }
    inputs = json.loads(payload["messages"][1]["content"])
    assert inputs["topic"]["id"] == script_topic.id
    assert inputs["source_cards"] == script_data["sources"]
    assert inputs["cta"] == settings.script_cta
    assert "недоверенные данные" in payload["messages"][0]["content"]
    assert result.to_dict() == script_data


@pytest.mark.parametrize("failure", ["json", "schema", "words", "source", "structure"])
def test_invalid_json_or_content_retries_then_succeeds(monkeypatch, settings, script_topic, script_data, failure):
    bad = copy.deepcopy(script_data)
    if failure == "json":
        bad = "```json\n" + json.dumps(bad) + "\n```"
    elif failure == "schema":
        del bad["caption"]
    elif failure == "words":
        bad["voiceover"] = "Слишком коротко"
    elif failure == "source":
        bad["sources"][0]["citation"] = "Выдумка"
    else:
        bad["voiceover"] = bad["voiceover"].replace("\n\n", " ")
    post = Mock(side_effect=[completion(bad), completion(script_data)])
    sleep = Mock()
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.openrouter_client.time.sleep", sleep)
    assert generate_script(script_topic, settings).to_dict() == script_data
    assert post.call_count == 2
    sleep.assert_called_once_with(0)


def test_schema_and_transport_share_one_retry_budget(monkeypatch, settings, script_topic, script_data, caplog):
    bad = copy.deepcopy(script_data)
    bad["caption"] = 1
    post = Mock(side_effect=[completion(bad), httpx.Response(429, text="test-only-key"), completion("test-only-key")])
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(OpenRouterError, match="after 3 attempts") as error:
        generate_script(script_topic, settings)
    assert post.call_count == 3
    assert "test-only-key" not in str(error.value) + caplog.text
    assert not settings.drafts_dir.exists()


def test_permanent_provider_error_is_not_retried(monkeypatch, settings, script_topic):
    post = Mock(return_value=httpx.Response(401, text="test-only-key"))
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(OpenRouterError, match="HTTP 401"):
        generate_script(script_topic, settings)
    assert post.call_count == 1


def test_load_one_or_explicit_topic(report_file, script_topic):
    assert load_script_topic(report_file) == script_topic
    data = json.loads(report_file.read_text())
    data["selected_topics"].append(topic_to_dict(replace(script_topic, id="second")))
    report_file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="--topic-id"):
        load_script_topic(report_file)
    assert load_script_topic(report_file, "second").id == "second"
    with pytest.raises(ValueError, match="absent"):
        load_script_topic(report_file, "unknown")


@pytest.mark.parametrize("bad", [
    {}, {"status": []}, {"status": "failed", "selected_topics": []},
    {"status": "ok", "selected_topics": []},
    {"status": "ok", "selected_topics": [None]},
    {"status": "ok", "selected_topics": [{"id": "only"}]},
    {"status": "ok", "selected_topics": [{"id": 3}]},
    {"status": "ok", "selected_topics": [{"id": "a"}, {"id": "a"}]},
])
def test_malformed_report_fails_cleanly(tmp_path, bad):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_script_topic(path)


def test_partial_report_allowed(report_file):
    report_file.write_text(report_file.read_text().replace('"ok"', '"partial"'))
    assert load_script_topic(report_file).id == "fixture-topic"


@pytest.mark.parametrize("field,value", [
    ("published_at", "2026-10-22T12:00:00"), ("source_id", None),
    ("links", [{"url": "https://media.example/other", "text": 4}]), ("text", 3),
])
def test_invalid_article_data_is_a_clean_input_error(report_file, field, value):
    data = json.loads(report_file.read_text())
    data["selected_topics"][0]["articles"][0][field] = value
    report_file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid articles"):
        load_script_topic(report_file)


def test_save_is_atomic_unique_and_never_overwrites(monkeypatch, settings, script_topic, script_data, review_payload):
    post = Mock(return_value=completion(script_data))
    monkeypatch.setattr(httpx, "post", post)
    script = generate_script(script_topic, settings)
    post.return_value = completion(review_payload(script, script_topic, settings))
    review = review_script(script, script_topic, settings)
    first = save_script(script, script_topic, settings, review=review)
    second = save_script(script, script_topic, settings, review=review)
    assert first != second
    assert json.loads(first.read_text()) == script_data
    with pytest.raises(FileExistsError):
        save_script(script, script_topic, settings, first, review=review)
    assert json.loads(first.read_text()) == script_data
    assert len(list(settings.drafts_dir.iterdir())) == 4  # two scripts and their audits


def test_failed_save_cleans_temporary_file(monkeypatch, settings, script_topic, script_data, review_payload):
    post = Mock(return_value=completion(script_data))
    monkeypatch.setattr(httpx, "post", post)
    script = generate_script(script_topic, settings)
    post.return_value = completion(review_payload(script, script_topic, settings))
    review = review_script(script, script_topic, settings)
    monkeypatch.setattr("app.script_generator.os.link", Mock(side_effect=OSError("fixture disk failure")))
    with pytest.raises(OSError):
        save_script(script, script_topic, settings, review=review)
    assert list(settings.drafts_dir.iterdir()) == []


def setup_cli(monkeypatch, settings):
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=settings))


def test_cli_json_and_file_match_without_marking_used(monkeypatch, settings, report_file, script_topic, script_data, capsys, tmp_path, review_payload):
    setup_cli(monkeypatch, settings)
    script = parse_script(script_data, script_topic, settings)
    post = Mock(side_effect=[completion(script_data), completion(review_payload(script, script_topic, settings))])
    monkeypatch.setattr(httpx, "post", post)
    history_path = tmp_path / "history.sqlite3"
    with TopicHistory(history_path) as history:
        history.save_selected([script_topic])
    before = history_path.read_bytes()
    output = tmp_path / "result.json"
    assert main(["script", "--input", str(report_file), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out) == script_data == json.loads(output.read_text())
    assert json.loads(output.with_suffix(".review.json").read_text())["review"]["status"] == "checked"
    assert post.call_count == 2
    assert history_path.read_bytes() == before
    with TopicHistory(history_path) as history:
        assert history.used_topics() == []


def test_cli_default_input_and_output(monkeypatch, settings, report_file, script_data, script_topic, capsys, tmp_path, review_payload):
    setup_cli(monkeypatch, settings)
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    Path("data/collected_topics.json").write_bytes(report_file.read_bytes())
    script = parse_script(script_data, script_topic, settings)
    monkeypatch.setattr(httpx, "post", Mock(side_effect=[completion(script_data), completion(review_payload(script, script_topic, settings))]))
    assert main(["script"]) == 0
    assert json.loads(capsys.readouterr().out) == script_data
    assert len([path for path in settings.drafts_dir.glob("reel-script-*.json") if not path.name.endswith(".review.json")]) == 1


@pytest.mark.parametrize("failure", ["invalid_json", "missing_key", "missing_input", "existing_output"])
def test_cli_failures_leave_no_new_script(monkeypatch, settings, report_file, capsys, tmp_path, failure):
    output = tmp_path / "result.json"
    if failure == "missing_key":
        settings = replace(settings, openrouter_api_key="")
    setup_cli(monkeypatch, settings)
    post = Mock(return_value=completion("not-json"))
    monkeypatch.setattr(httpx, "post", post)
    if failure == "missing_input":
        report_file.unlink()
    if failure == "existing_output":
        output.write_text("preserve me")
    assert main(["script", "--input", str(report_file), "--output", str(output)]) == 2
    assert capsys.readouterr().out == ""
    assert not settings.drafts_dir.exists()
    if failure == "existing_output":
        assert output.read_text() == "preserve me"
    else:
        assert not output.exists()
    assert post.call_count == (3 if failure == "invalid_json" else 0)
