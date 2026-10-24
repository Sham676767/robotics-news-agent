from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import httpx
import pytest
from botocore.exceptions import ClientError

from app.instagram_client import InstagramClient, InstagramError, PublishUncertain, retry_after_seconds
from app.publishing_config import PublishingSettings, public_video_url
from app.video_storage import S3VideoStorage, StorageError, StoredVideo


@pytest.fixture
def publication_config():
    return PublishingSettings(instagram_user_id="12345", instagram_api_version="v25.0",
                              instagram_access_token="fixture-instagram-secret-token", retry_base_seconds=1,
                              retry_max_seconds=10, poll_interval_seconds=0, poll_attempts=3,
                              s3_endpoint="https://s3.example.org", s3_bucket="test-videos",
                              s3_access_key="fixture-access-key", s3_secret_key="fixture-s3-secret-key")


def test_reels_create_poll_publish_and_bearer_headers(publication_config):
    request = Mock(side_effect=[httpx.Response(200, json={"id": "200"}),
                               httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
                               httpx.Response(200, json={"status_code": "FINISHED"}),
                               httpx.Response(200, json={"id": "300"})])
    sleep = Mock()
    client = InstagramClient(publication_config, request=request, sleep=sleep)
    assert client.create_reel("https://cdn.example.org/video.mp4", "Учебная подпись") == "200"
    assert client.wait_ready("200") == "FINISHED"
    assert client.publish("200") == "300"
    calls = request.call_args_list
    assert calls[0].args == ("POST", "https://graph.instagram.com/v25.0/12345/media")
    assert calls[0].kwargs["data"] == {"media_type": "REELS", "video_url": "https://cdn.example.org/video.mp4",
                                      "caption": "Учебная подпись", "share_to_feed": "true"}
    for call in calls:
        assert call.kwargs["headers"] == {"Authorization": "Bearer fixture-instagram-secret-token"}
        assert "fixture-instagram-secret-token" not in str(call.args) + str(call.kwargs["params"]) + str(call.kwargs["data"])
        assert call.kwargs["follow_redirects"] is False
    sleep.assert_called_once_with(0)


def test_facebook_login_uses_its_own_host(publication_config):
    request = Mock(return_value=httpx.Response(200, json={"status_code": "PUBLISHED"}))
    client = InstagramClient(replace(publication_config, instagram_login="facebook"), request=request)
    assert client.status("200") == "PUBLISHED"
    assert request.call_args.args[1].startswith("https://graph.facebook.com/")


def test_retry_backoff_and_retry_after(publication_config):
    request = Mock(side_effect=[httpx.Response(429, headers={"Retry-After": "3"}, json={"error": {"code": 4}}),
                               httpx.Response(500, json={}), httpx.Response(200, json={"id": "200"})])
    sleep = Mock()
    client = InstagramClient(publication_config, request=request, sleep=sleep)
    assert client.create_reel("https://cdn.example.org/video.mp4", "caption") == "200"
    assert [call.args[0] for call in sleep.call_args_list] == [3, 2]


def test_long_retry_after_is_not_capped_into_early_retry(publication_config):
    request = Mock(return_value=httpx.Response(429, headers={"Retry-After": "100"}))
    sleep = Mock()
    with pytest.raises(InstagramError) as error:
        InstagramClient(publication_config, request=request, sleep=sleep).status("200")
    assert error.value.retry_after == 100
    request.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("code,subcode", [(190, 0), (10, 0), (200, 0), (4, 2207051), (9, 2207042)])
def test_permanent_errors_are_sanitized_and_not_retried(publication_config, code, subcode, caplog):
    request = Mock(return_value=httpx.Response(400, json={"error": {"code": code, "error_subcode": subcode,
                    "message": publication_config.instagram_access_token, "is_transient": True}}))
    with pytest.raises(InstagramError) as error:
        InstagramClient(publication_config, request=request).status("200")
    request.assert_called_once()
    assert publication_config.instagram_access_token not in str(error.value) + caplog.text


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("secret"), httpx.WriteError("secret"),
                                    httpx.Response(502), httpx.Response(200, text="bad"), httpx.Response(200, json={})])
def test_uncertain_publish_is_never_automatically_repeated(publication_config, failure):
    request = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    with pytest.raises(PublishUncertain):
        InstagramClient(publication_config, request=request).publish("200")
    request.assert_called_once()


def test_publish_explicit_temporary_rejection_can_retry(publication_config):
    request = Mock(side_effect=[httpx.Response(429, json={"error": {"code": 4}}), httpx.Response(200, json={"id": "300"})])
    sleep = Mock()
    assert InstagramClient(publication_config, request=request, sleep=sleep).publish("200") == "300"
    sleep.assert_called_once_with(1)


@pytest.mark.parametrize("status,reason", [("EXPIRED", "container_expired"), ("ERROR", "container_error"),
                                           ("IN_PROGRESS", "processing_pending"), ("NONSENSE", "unknown_container_status")])
def test_processing_error_expiry_and_bounded_poll(publication_config, status, reason):
    request = Mock(return_value=httpx.Response(200, json={"status_code": status}))
    with pytest.raises(InstagramError, match=reason):
        InstagramClient(publication_config, request=request, sleep=Mock()).wait_ready("200")
    assert request.call_count == (3 if status == "IN_PROGRESS" else 1)


@pytest.mark.parametrize("used,total,allowed", [(2, 3, True), (3, 3, False), (5, 3, False)])
def test_quota_comes_from_response_not_hardcoded(publication_config, used, total, allowed):
    request = Mock(return_value=httpx.Response(200, json={"data": [{"quota_usage": used, "config": {"quota_total": total}}]}))
    client = InstagramClient(publication_config, request=request)
    if allowed:
        client.check_quota()
    else:
        with pytest.raises(InstagramError, match="quota_exhausted"):
            client.check_quota()


@pytest.mark.parametrize("url", ["http://cdn.example.org/x", "https://localhost/x", "https://127.0.0.1/x",
    "https://10.0.0.1/x", "https://192.168.1.2/x", "https://user:password@cdn.example.org/x", "file:///video.mp4"])
def test_nonpublic_urls_rejected(url):
    with pytest.raises(ValueError):
        public_video_url(url)


def test_s3_presign_upload_delete_and_content_type(publication_config, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fixture")
    key = "reels/reel-" + "a" * 32 + "/" + "b" * 64 + ".mp4"
    client = Mock()
    client.generate_presigned_url.return_value = "https://s3.example.org/video?X-Amz-Signature=secret"
    storage = S3VideoStorage(publication_config, client=client)
    result = storage.upload(video, key)
    client.upload_file.assert_called_once_with(str(video), "test-videos", key, ExtraArgs={"ContentType": "video/mp4"})
    assert client.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 7200
    assert result.expires_at > datetime.now(timezone.utc) + timedelta(seconds=7100)
    assert "secret" not in repr(result)
    storage.delete(key)
    client.delete_object.assert_called_once_with(Bucket="test-videos", Key=key)


def test_public_bucket_does_not_need_signature(publication_config, tmp_path):
    key = "reels/reel-" + "a" * 32 + "/" + "b" * 64 + ".mp4"
    client = Mock()
    result = S3VideoStorage(replace(publication_config, s3_public_base_url="https://cdn.example.org"), client=client).upload(tmp_path / "v.mp4", key)
    assert result.url == "https://cdn.example.org/" + key and result.expires_at is None
    client.generate_presigned_url.assert_not_called()


def test_sdk_uses_explicit_endpoint_credentials_and_bounded_standard_retries(publication_config, monkeypatch):
    factory = Mock()
    monkeypatch.setattr("app.video_storage.boto3.client", factory)
    S3VideoStorage(publication_config)
    kwargs = factory.call_args.kwargs
    assert kwargs["endpoint_url"] == publication_config.s3_endpoint
    assert kwargs["aws_secret_access_key"] == publication_config.s3_secret_key
    assert kwargs["config"].retries == {"mode": "standard", "total_max_attempts": 3}


def test_storage_error_does_not_leak_service_response(publication_config, tmp_path):
    client = Mock()
    client.upload_file.side_effect = ClientError({"Error": {"Code": "Denied", "Message": "fixture-s3-secret-key"}}, "PutObject")
    with pytest.raises(StorageError) as error:
        S3VideoStorage(publication_config, client=client).upload(tmp_path / "v.mp4", "reels/reel-" + "a" * 32 + "/" + "b" * 64 + ".mp4")
    assert "fixture-s3-secret-key" not in str(error.value)


def test_retry_after_date_and_invalid_values():
    from email.utils import format_datetime
    assert 0 < retry_after_seconds(format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60))) <= 60
    assert retry_after_seconds("NaN") is None
    assert retry_after_seconds("invalid") is None
