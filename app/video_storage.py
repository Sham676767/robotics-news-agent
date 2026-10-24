"""S3-compatible video storage with explicit credentials and safe retry policy."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from boto3.exceptions import S3UploadFailedError

from app.publishing_config import PublishingSettings


class StorageError(RuntimeError):
    """Storage failure without service messages, URLs or credentials."""


@dataclass(frozen=True, slots=True)
class StoredVideo:
    key: str
    url: str = field(repr=False)
    expires_at: datetime | None = None


class VideoStorage(Protocol):
    def upload(self, path: Path, key: str) -> StoredVideo: ...
    def delete(self, key: str) -> None: ...


def valid_key(key: str) -> str:
    if not re.fullmatch(r"reels/reel-[0-9a-f]{32}/[0-9a-f]{64}\.mp4", key):
        raise ValueError("Invalid video object key")
    return key


class S3VideoStorage:
    def __init__(self, settings: PublishingSettings, *, client: Any = None) -> None:
        settings.require_storage()
        self.settings = settings
        # Explicit values prevent ambient AWS profiles/instance metadata from supplying credentials.
        self.client = client if client is not None else boto3.client(
            "s3", endpoint_url=settings.s3_endpoint, region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4", connect_timeout=settings.api_timeout,
                          read_timeout=settings.api_timeout,
                          retries={"mode": "standard", "total_max_attempts": settings.max_attempts},
                          s3={"addressing_style": settings.s3_addressing_style},
                          request_checksum_calculation="when_required", response_checksum_validation="when_required"),
        )

    def upload(self, path: Path, key: str) -> StoredVideo:
        valid_key(key)
        try:
            self.client.upload_file(str(path), self.settings.s3_bucket, key, ExtraArgs={"ContentType": "video/mp4"})
            if self.settings.s3_public_base_url:
                return StoredVideo(key, self.settings.s3_public_base_url + "/" + quote(key, safe="/"))
            url = self.client.generate_presigned_url("get_object", Params={"Bucket": self.settings.s3_bucket, "Key": key},
                                                    ExpiresIn=self.settings.s3_presign_ttl_seconds, HttpMethod="GET")
            return StoredVideo(key, url, datetime.now(timezone.utc) + timedelta(seconds=self.settings.s3_presign_ttl_seconds))
        except (BotoCoreError, ClientError, S3UploadFailedError, OSError):
            raise StorageError("S3 upload or URL creation failed; check credentials, endpoint and bucket permissions") from None

    def delete(self, key: str) -> None:
        valid_key(key)
        try:
            self.client.delete_object(Bucket=self.settings.s3_bucket, Key=key)
        except (BotoCoreError, ClientError):
            raise StorageError("S3 cleanup failed; publication remains recorded and cleanup can be retried") from None
