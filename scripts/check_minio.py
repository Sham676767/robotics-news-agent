"""Manual local-only S3 round trip. Run as python -m scripts.check_minio VIDEO."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.config import Settings
from app.reel_drafts import checksum
from app.secret_logging import protect_logs
from app.video_storage import S3VideoStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload, download by signed URL, verify and delete one local MinIO test object")
    parser.add_argument("video", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    protect_logs(settings)
    endpoint = urlsplit(settings.publishing.s3_endpoint)
    if endpoint.hostname not in {"localhost", "127.0.0.1", "host.docker.internal"}:
        raise ValueError("This smoke check is restricted to a local MinIO endpoint")
    if settings.publishing.s3_public_base_url:
        raise ValueError("Clear S3_PUBLIC_BASE_URL for the local presigned URL check")
    storage = S3VideoStorage(settings.publishing)
    expected = checksum(args.video)
    key = f"reels/reel-{uuid4().hex}/{expected}.mp4"
    try:
        stored = storage.upload(args.video, key)
        actual = hashlib.sha256()
        with httpx.stream("GET", stored.url, timeout=30) as response:
            if response.status_code != 200:
                raise ValueError("Local MinIO download failed")
            for chunk in response.iter_bytes():
                actual.update(chunk)
        if actual.hexdigest() != expected:
            raise ValueError("Local MinIO checksum mismatch")
    except httpx.HTTPError:
        raise ValueError("Local MinIO request failed; signed URL is not logged") from None
    finally:
        storage.delete(key)
    print("Local MinIO upload, presigned GET, checksum and cleanup passed")


if __name__ == "__main__":
    main()
