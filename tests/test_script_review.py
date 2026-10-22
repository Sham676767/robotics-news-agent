import copy
import json
from dataclasses import asdict, replace
from unittest.mock import Mock

import httpx
import pytest

from app.cli import main
from app.config import Settings
from app.reel_script import parse_script, topic_sources
from app.script_generator import save_script
from app.script_review import parse_review, primary_texts, review_claims, review_script
from app.topics import topic_to_dict


def completion(data):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data, ensure_ascii=False)}}]})


@pytest.fixture
def review_settings(tmp_path):
    return Settings(openrouter_api_key="test-only-key", openrouter_model="fixture/reviewer",
                    retry_base_seconds=0, retry_max_seconds=0, drafts_dir=tmp_path / "drafts")


def test_review_prompt_uses_source_text_separate_request_and_configured_model(monkeypatch, script_data, script_topic, review_settings, review_payload):
    script = parse_script(script_data, script_topic, review_settings)
    payload = review_payload(script, script_topic, review_settings)
    post = Mock(return_value=completion(payload))
    monkeypatch.setattr(httpx, "post", post)
    review = review_script(script, script_topic, review_settings)
    assert review.passed
    assert not review.to_dict()["publication_allowed"]
    assert review.to_dict()["human_review_required"]
    sent = post.call_args.kwargs["json"]
    assert sent["model"] == review_settings.openrouter_model
    assert sent["response_format"]["json_schema"]["name"] == "script_review"
    user = json.loads(sent["messages"][1]["content"])
    assert user["primary_sources"][0]["text"] == script_topic.references[0].content
    assert user["primary_sources"][0]["text"] != script_topic.references[0].excerpt
    assert len(user["claims"]) == len(review.claims)
    post.assert_called_once()


@pytest.mark.parametrize("verdict", ["contradicted", "insufficient"])
def test_negative_verdict_is_not_regenerated_until_it_passes(monkeypatch, script_data, script_topic, review_settings, review_payload, verdict):
    script = parse_script(script_data, script_topic, review_settings)
    data = review_payload(script, script_topic, review_settings)
    data["claims"][0].update(verdict=verdict, reason="Утверждение не соответствует первоисточнику.")
    post = Mock(return_value=completion(data))
    monkeypatch.setattr(httpx, "post", post)
    review = review_script(script, script_topic, review_settings)
    assert not review.passed
    assert f"llm_{verdict}" in {issue.code for issue in review.issues}
    post.assert_called_once()


@pytest.mark.parametrize("change", [
    "missing_claim", "duplicate_claim", "unknown_claim", "unknown_url", "news_url", "fake_quote",
    "empty_quote", "short_quote", "all_non_factual", "norm_non_factual", "empty_reason", "unknown_verdict", "extra_field",
])
def test_verifier_cannot_omit_claims_or_fabricate_evidence(script_data, script_topic, review_settings, review_payload, change):
    script = parse_script(script_data, script_topic, review_settings)
    data = review_payload(script, script_topic, review_settings)
    first = data["claims"][0]
    if change == "missing_claim":
        data["claims"].pop()
    elif change == "duplicate_claim":
        data["claims"][-1] = copy.deepcopy(first)
    elif change == "unknown_claim":
        first["id"] = "unknown"
    elif change in {"unknown_url", "news_url"}:
        first["source_url"] = script_topic.articles[0].url if change == "news_url" else "https://other.example/"
    elif change == "fake_quote":
        first["quote"] = "Такой цитаты в первоисточнике нет."
    elif change == "empty_quote":
        first["quote"] = ""
    elif change == "short_quote":
        first["quote"] = script_topic.references[0].content[0]
    elif change == "all_non_factual":
        for item in data["claims"]:
            item.update(verdict="non_factual", source_url="", quote="")
    elif change == "norm_non_factual":
        data["claims"][-1].update(verdict="non_factual", source_url="", quote="")
    elif change == "empty_reason":
        first["reason"] = "  "
    elif change == "unknown_verdict":
        first["verdict"] = "approved"
    else:
        first["confidence"] = 1
    with pytest.raises(ValueError):
        parse_review(data, review_claims(script, review_settings), primary_texts(script_topic))


def test_non_factual_question_is_allowed_with_reason(script_data, script_topic, review_settings, review_payload):
    script = parse_script(script_data, script_topic, review_settings)
    data = review_payload(script, script_topic, review_settings)
    data["claims"][0].update(verdict="non_factual", source_url="", quote="", reason="Вопрос без утверждения факта.")
    assert parse_review(data, review_claims(script, review_settings), primary_texts(script_topic))[0].verdict == "non_factual"


def test_all_insufficient_is_a_valid_negative_report(script_data, script_topic, review_settings, review_payload):
    script = parse_script(script_data, script_topic, review_settings)
    data = review_payload(script, script_topic, review_settings)
    for item in data["claims"]:
        item.update(verdict="insufficient", source_url="", quote="", reason="Недостаточно текста.")
    assert all(check.verdict == "insufficient" for check in parse_review(data, review_claims(script, review_settings), {}))


def test_custom_cta_and_hashtags_are_also_reviewed(script_data, script_topic, review_settings):
    script = parse_script(script_data, script_topic, review_settings)
    custom = "Вы получите возмещение"
    altered = replace(script, voiceover=script.voiceover.replace(review_settings.script_cta, custom))
    claims = review_claims(altered, replace(review_settings, script_cta=custom))
    assert any(claim.text == custom for claim in claims)
    assert any(claim.field == "hashtags" for claim in claims)


def test_invalid_review_retries_then_succeeds(monkeypatch, script_data, script_topic, review_settings, review_payload):
    script = parse_script(script_data, script_topic, review_settings)
    post = Mock(side_effect=[completion({"approved": True}), completion(review_payload(script, script_topic, review_settings))])
    monkeypatch.setattr(httpx, "post", post)
    assert review_script(script, script_topic, review_settings).passed
    assert post.call_count == 2


@pytest.mark.parametrize("bad", [httpx.Response(503, text="test-only-key"), completion({"approved": True})])
def test_unavailable_or_unverifiable_review_is_blocking(monkeypatch, script_data, script_topic, review_settings, bad, caplog):
    script = parse_script(script_data, script_topic, review_settings)
    post = Mock(return_value=bad)
    monkeypatch.setattr(httpx, "post", post)
    review = review_script(script, script_topic, review_settings)
    assert not review.passed
    assert "review_unavailable" in {issue.code for issue in review.issues}
    assert post.call_count == review_settings.openrouter_max_attempts
    assert "test-only-key" not in caplog.text


@pytest.mark.parametrize("failure", ["categorical", "missing_norm", "missing_primary"])
def test_llm_approval_cannot_override_local_block(monkeypatch, script_data, script_topic, review_settings, review_payload, failure):
    if failure == "categorical":
        script_data["caption"] = "Вам точно положено возмещение."
    elif failure == "missing_norm":
        script_topic = replace(script_topic, references=(replace(script_topic.references[0], content="Учебный документ без статьи."),))
    else:
        script_topic = replace(script_topic, references=(replace(script_topic.references[0], content=""),))
    script_data["sources"] = [asdict(source) for source in topic_sources(script_topic)]
    script = parse_script(script_data, script_topic, review_settings)
    data = review_payload(script, script_topic, review_settings)
    if failure == "categorical":
        for item in data["claims"]:
            if item["verdict"] == "supported":
                item["quote"] = script_topic.references[0].content.splitlines()[0]
    monkeypatch.setattr(httpx, "post", Mock(return_value=completion(data)))
    review = review_script(script, script_topic, review_settings)
    assert not review.passed
    assert {issue.code for issue in review.issues} & {"categorical_claim", "missing_norm", "missing_primary_text"}


@pytest.mark.parametrize("failure", ["contradiction", "insufficient", "timeout", "malformed", "categorical"])
def test_cli_quarantines_with_reason_and_never_writes_normal_output(monkeypatch, tmp_path, script_data, script_topic, review_settings, review_payload, capsys, failure):
    if failure == "categorical":
        script_data["caption"] = "Вам точно положено возмещение."
    script = parse_script(script_data, script_topic, review_settings)
    data = review_payload(script, script_topic, review_settings)
    expected = "categorical_claim"
    if failure in {"contradiction", "insufficient"}:
        verdict = "contradicted" if failure == "contradiction" else "insufficient"
        data["claims"][0].update(verdict=verdict, reason="Есть расхождение с источником.")
        expected = f"llm_{verdict}"
    if failure == "categorical":
        for item in data["claims"]:
            if item["verdict"] == "supported":
                item["quote"] = script_topic.references[0].content.splitlines()[0]
    if failure in {"timeout", "malformed"}:
        rejected = httpx.ConnectTimeout("test-only-key") if failure == "timeout" else completion({"approved": True})
        responses = [completion(script_data), *([rejected] * review_settings.openrouter_max_attempts)]
        expected = "review_unavailable"
    else:
        responses = [completion(script_data), completion(data)]
    post = Mock(side_effect=responses)
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=review_settings))
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"status": "ok", "selected_topics": [topic_to_dict(script_topic)]}))
    output = tmp_path / "ready.json"
    assert main(["script", "--input", str(source), "--output", str(output)]) == 3
    assert capsys.readouterr().out == ""
    assert not output.exists() and not output.with_suffix(".review.json").exists()
    held = list((review_settings.drafts_dir / "quarantine").glob("*.json"))
    assert len(held) == 1
    bundle = json.loads(held[0].read_text())
    assert bundle["script"] == script_data
    assert expected in {issue["code"] for issue in bundle["review"]["issues"]}
    assert not bundle["review"]["eligible_for_next_stage"]
    assert not bundle["review"]["publication_allowed"]


def test_review_is_bound_to_script_and_actual_source_snapshot(monkeypatch, script_data, script_topic, review_settings, review_payload):
    script = parse_script(script_data, script_topic, review_settings)
    monkeypatch.setattr(httpx, "post", Mock(return_value=completion(review_payload(script, script_topic, review_settings))))
    review = review_script(script, script_topic, review_settings)
    with pytest.raises(ValueError, match="does not match"):
        save_script(replace(script, caption="Изменённая подпись"), script_topic, review_settings, review=review)
    for altered in (
        replace(script_topic, articles=(replace(script_topic.articles[0], text="Изменённый источник"),)),
        replace(script_topic, references=(replace(script_topic.references[0], content=script_topic.references[0].content + " Изменение."),)),
    ):
        with pytest.raises(ValueError, match="does not match"):
            save_script(script, altered, review_settings, review=review)
    assert not review_settings.drafts_dir.exists()


def test_rejected_review_cannot_be_saved_via_library(monkeypatch, script_data, script_topic, review_settings, review_payload):
    script = parse_script(script_data, script_topic, review_settings)
    data = review_payload(script, script_topic, review_settings)
    data["claims"][0].update(verdict="contradicted", reason="Расхождение.")
    monkeypatch.setattr(httpx, "post", Mock(return_value=completion(data)))
    review = review_script(script, script_topic, review_settings)
    with pytest.raises(ValueError, match="rejected"):
        save_script(script, script_topic, review_settings, review=review)
    assert not review_settings.drafts_dir.exists()


def test_second_file_failure_rolls_back_review_audit(monkeypatch, script_data, script_topic, review_settings, review_payload):
    import os
    script = parse_script(script_data, script_topic, review_settings)
    monkeypatch.setattr(httpx, "post", Mock(return_value=completion(review_payload(script, script_topic, review_settings))))
    review = review_script(script, script_topic, review_settings)
    link = os.link
    count = 0
    def fail_second(source, target):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("fixture disk failure")
        return link(source, target)
    monkeypatch.setattr("app.script_generator.os.link", fail_second)
    with pytest.raises(OSError):
        save_script(script, script_topic, review_settings, review=review)
    assert list(review_settings.drafts_dir.iterdir()) == []
