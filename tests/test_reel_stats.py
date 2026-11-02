import json
from unittest.mock import Mock

import httpx
import pytest

from app.cli import main
from app.config import Settings
from app.instagram_client import INSIGHT_METRICS, InstagramClient, InstagramError
from app.publishing_config import PublishingSettings
from app.reel_drafts import checksum, read_json, write_json
from app.reel_stats import collect_stats, comparison
from app.script_review import digest


@pytest.fixture
def stats_settings(tmp_path):
    return Settings(drafts_dir=tmp_path / "drafts", publishing=PublishingSettings(instagram_user_id="123", instagram_api_version="v25.0", instagram_access_token="test-secret-token", retry_base_seconds=0, retry_max_seconds=0))


@pytest.fixture
def published(stats_settings):
    root = stats_settings.drafts_dir / "reels"
    def make(index=1, format="checklist", hook="Проверьте договор", views=1000):
        folder = root / f"reel-{index:032x}"
        folder.mkdir(parents=True)
        script = {"hook": hook, "voiceover": hook + "\n\nСуть\n\nДействия\n\nНапишите РАЗБОР"}
        write_json(folder / "script.json", script)
        write_json(folder / "script.review.json", {"topic": {"title": "Синтетическая тема"}})
        write_json(folder / "render.json", {"schema_version": 2, "script_sha256": digest(script), "topic": "Синтетическая тема", "format": format,
            "hook": hook, "hook_variants": [hook, "Другой учебный хук"], "selected_hook": 0, "duration_seconds": 39,
            "cta": "Напишите РАЗБОР", "cta_keyword": "РАЗБОР"})
        manifest = {"mode": "live", "assets": {name: checksum(folder / name) for name in ("render.json", "script.json")}}
        write_json(folder / "draft.json", manifest)
        write_json(folder / "state.json", {"status": "published", "media_id": str(200 + index), "published_at": "2026-11-01T10:00:00+00:00",
            "approval": {"account": stats_settings.publishing.account, "bundle_sha256": digest(manifest)}})
        return folder
    return make


def metric_response(name, value=5):
    return httpx.Response(200, json={"data": [{"name": name, "period": "lifetime", "values": [{"value": value}]}]})


def test_insights_request_only_supported_metrics_with_bearer(stats_settings):
    request = Mock(side_effect=[metric_response(name) for name in INSIGHT_METRICS])
    values, missing = InstagramClient(stats_settings.publishing, request=request).media_insights("201")
    assert values == {name: 5 for name in INSIGHT_METRICS} and not missing
    assert request.call_count == 4
    assert all(call.args[0] == "GET" and call.args[1].endswith("/201/insights") for call in request.call_args_list)
    assert all("messages" not in call.kwargs["params"]["metric"] for call in request.call_args_list)
    assert "Authorization" in request.call_args.kwargs["headers"]
    assert "test-secret-token" not in request.call_args.args[1]


@pytest.mark.parametrize("bad", [None, True, -1, 1.5, "5", {}, []])
def test_missing_or_invalid_metric_is_not_reported_as_zero(stats_settings, bad):
    request = Mock(side_effect=[metric_response("views", bad), *[metric_response(name, 0) for name in INSIGHT_METRICS[1:]]])
    values, missing = InstagramClient(stats_settings.publishing, request=request).media_insights("201")
    assert values["views"] is None and missing["views"] == "missing_or_invalid_metric"
    assert values["saved"] == 0


@pytest.mark.parametrize("payload", [{"data": []}, {"data": [None]}, {"data": [{"name": "views", "values": []}]},
    {"data": [{"name": "wrong", "values": [{"value": 1}]}]}, {"data": [{"name": "views", "total_value": {"value": 2}}, {"name": "views", "total_value": {"value": 3}}]}])
def test_empty_wrong_or_duplicate_response_rejected(stats_settings, payload):
    request = Mock(side_effect=[httpx.Response(200, json=payload), *[metric_response(name) for name in INSIGHT_METRICS[1:]]])
    assert InstagramClient(stats_settings.publishing, request=request).media_insights("201")[0]["views"] is None


def test_unsupported_metric_does_not_discard_other_metrics(stats_settings):
    request = Mock(side_effect=[metric_response("views", 100), metric_response("saved", 2), metric_response("shares", 1), httpx.Response(400, json={"error": {"code": 100}})])
    values, missing = InstagramClient(stats_settings.publishing, request=request).media_insights("201")
    assert values == {"views": 100, "saved": 2, "shares": 1, "reposts": None}
    assert missing == {"reposts": "not_supported_or_rejected"}


def test_stats_join_exact_hooks_formats_dates_without_writing(stats_settings, published):
    published()
    published(2, "question_answer", "Другой хук")
    before = {str(path): path.read_bytes() for path in stats_settings.drafts_dir.rglob("*") if path.is_file()}
    client = Mock(spec=InstagramClient)
    client.media_insights.side_effect = [({"views": 1000, "saved": 10, "shares": 5, "reposts": 1}, {}), ({"views": 100, "saved": 5, "shares": 5, "reposts": 0}, {})]
    result = collect_stats(stats_settings, client=client)
    assert result["status"] == "ok"
    assert result["by_format"][0]["format"] == "question_answer"
    assert result["by_format"][0]["saves_per_1000_views"] == 50
    assert result["reels"][0]["publication_date"] == "2026-11-01T10:00:00+00:00"
    assert all(row["messages"] is None for row in result["reels"])
    assert "не ноль" in result["messages_note"] or "не ноль".replace("не ", "а не ") in result["messages_note"]
    assert before == {str(path): path.read_bytes() for path in stats_settings.drafts_dir.rglob("*") if path.is_file()}


def test_comparison_excludes_incomplete_pairs_and_zero_denominators():
    rows = [{"format": "a", "views": 1000, "saved": None, "shares": 100}, {"format": "a", "views": 10, "saved": 1, "shares": 0}, {"format": "b", "views": 0, "saved": 0, "shares": 0}]
    result = comparison(rows, "format")
    assert result[0]["views"] == 10 and result[0]["comparable_reels"] == 1
    assert result[0]["save_share_rate"] == .1
    assert result[1]["save_share_rate"] is None
    only_missing = comparison([rows[0]], "format")[0]
    assert only_missing["views"] is None and only_missing["save_share_rate"] is None


def test_authorization_failure_is_sanitized_and_partial(stats_settings, published):
    published()
    client = Mock(spec=InstagramClient)
    client.media_insights.side_effect = InstagramError("authorization_or_account_restriction")
    result = collect_stats(stats_settings, client=client)
    assert result["status"] == "partial" and result["reels"][0]["views"] is None
    assert "test-secret-token" not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["stub", "account", "checksum", "date", "id"])
def test_bad_metadata_never_triggers_an_api_call(stats_settings, published, mutation):
    folder = published()
    state = read_json(folder / "state.json")
    if mutation == "stub":
        manifest = read_json(folder / "draft.json"); manifest["mode"] = "stub"; write_json(folder / "draft.json", manifest)
    elif mutation == "account": state["approval"]["account"]["user_id"] = "999"
    elif mutation == "checksum": (folder / "render.json").write_text("{}")
    elif mutation == "date": state["published_at"] = "2026-11-01"
    else: state["media_id"] = "../token"
    write_json(folder / "state.json", state)
    client = Mock(spec=InstagramClient)
    result = collect_stats(stats_settings, ids=[folder.name], client=client)
    assert result["status"] == "partial" and not result["reels"]
    client.media_insights.assert_not_called()


def test_stats_without_publications_needs_no_network_or_keys(tmp_path):
    result = collect_stats(Settings(drafts_dir=tmp_path))
    assert result["status"] == "no_data" and not result["reels"]


def test_stats_cli_json_new_snapshot_and_no_overwrite(monkeypatch, stats_settings, tmp_path, capsys):
    monkeypatch.setattr("app.cli.Settings.from_env", Mock(return_value=stats_settings))
    output = tmp_path / "stats.json"
    assert main(["stats", "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == json.loads(capsys.readouterr().out)
    before = output.read_bytes()
    assert main(["stats", "--output", str(output)]) == 2
    assert output.read_bytes() == before


def test_configured_cover_offset_sent_when_creating_container(stats_settings):
    request = Mock(return_value=httpx.Response(200, json={"id": "200"}))
    InstagramClient(stats_settings.publishing, request=request).create_reel("https://cdn.example.org/a.mp4", "Подпись", thumb_offset_ms=1500)
    assert request.call_args.kwargs["data"]["thumb_offset"] == "1500"
    with pytest.raises(ValueError):
        InstagramClient(stats_settings.publishing, request=request).create_reel("https://cdn.example.org/a.mp4", "Подпись", thumb_offset_ms=True)
