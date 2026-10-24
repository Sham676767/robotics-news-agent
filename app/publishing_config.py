"""Publication-only settings; credentials are never represented as text."""
from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit


def public_video_url(value: str) -> str:
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if url.scheme != "https" or not host or url.username or url.password or url.fragment:
            raise ValueError
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
            raise ValueError
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError
        except ValueError as exc:
            # A domain name is resolved by Meta later; no DNS/network in preflight.
            if re.fullmatch(r"[0-9.:]+", host):
                raise ValueError from exc
        if url.port not in (None, 443):
            raise ValueError
    except ValueError:
        raise ValueError("Video URL must use public HTTPS on port 443; local/private URLs are not reachable by Instagram") from None
    return value


@dataclass(frozen=True, slots=True)
class PublishingSettings:
    pipeline_mode: str = "live"
    instagram_login: str = "instagram"
    instagram_user_id: str = ""
    instagram_api_version: str = ""
    instagram_access_token: str = field(default="", repr=False)
    instagram_share_to_feed: bool = True
    api_timeout: float = 30.0
    max_attempts: int = 3
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 60.0
    poll_interval_seconds: float = 60.0
    poll_attempts: int = 5
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = field(default="", repr=False)
    s3_secret_key: str = field(default="", repr=False)
    s3_region: str = "us-east-1"
    s3_public_base_url: str = ""
    s3_presign_ttl_seconds: int = 7200
    s3_delete_after_publish: bool = True
    s3_addressing_style: str = "auto"

    def __post_init__(self) -> None:
        if self.pipeline_mode not in {"live", "stub"} or self.instagram_login not in {"instagram", "facebook"}:
            raise ValueError("Invalid PIPELINE_MODE or INSTAGRAM_LOGIN")
        if self.instagram_api_version and not re.fullmatch(r"v[0-9]+\.[0-9]+", self.instagram_api_version):
            raise ValueError("INSTAGRAM_API_VERSION must use vNN.N format")
        if self.instagram_user_id and not re.fullmatch(r"[0-9]+", self.instagram_user_id):
            raise ValueError("INSTAGRAM_USER_ID must contain digits only")
        for name in ("api_timeout", "poll_interval_seconds", "retry_base_seconds", "retry_max_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Publication {name} must be finite and non-negative")
        if self.api_timeout <= 0 or self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("Invalid publication timeout or retry range")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 10:
            raise ValueError("INSTAGRAM_MAX_ATTEMPTS must be 1–10")
        if type(self.poll_attempts) is not int or not 1 <= self.poll_attempts <= 60:
            raise ValueError("INSTAGRAM_POLL_ATTEMPTS must be 1–60")
        if type(self.s3_presign_ttl_seconds) is not int or not 600 <= self.s3_presign_ttl_seconds <= 604800:
            raise ValueError("S3_PRESIGN_TTL_SECONDS must be 600–604800")
        if self.s3_addressing_style not in {"auto", "path", "virtual"}:
            raise ValueError("S3_ADDRESSING_STYLE must be auto, path or virtual")

    @property
    def graph_base(self) -> str:
        host = "graph.instagram.com" if self.instagram_login == "instagram" else "graph.facebook.com"
        return f"https://{host}/{self.instagram_api_version}"

    @property
    def account(self) -> dict[str, str]:
        return {"login": self.instagram_login, "user_id": self.instagram_user_id}

    def require_account(self, *, token: bool = True) -> None:
        if not self.instagram_user_id or not self.instagram_api_version:
            raise ValueError("Configure INSTAGRAM_USER_ID and INSTAGRAM_API_VERSION")
        if token and not self.instagram_access_token:
            raise ValueError("Configure INSTAGRAM_ACCESS_TOKEN in .env")

    def require_storage(self) -> None:
        if not all((self.s3_endpoint, self.s3_bucket, self.s3_access_key, self.s3_secret_key, self.s3_region)):
            raise ValueError("Configure S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY and S3_REGION in .env")
        url = urlsplit(self.s3_endpoint)
        if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Invalid S3_ENDPOINT")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.s3_bucket):
            raise ValueError("Invalid S3_BUCKET name")
        if self.s3_public_base_url:
            public_video_url(self.s3_public_base_url)
            if urlsplit(self.s3_public_base_url).query:
                raise ValueError("S3_PUBLIC_BASE_URL must not contain query parameters")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> PublishingSettings:
        def boolean(name: str, default: bool) -> bool:
            raw = env.get(name, str(default)).lower().strip()
            if raw not in {"true", "false", "1", "0"}:
                raise ValueError(f"{name} must be true or false")
            return raw in {"true", "1"}
        try:
            return cls(
                pipeline_mode=env.get("PIPELINE_MODE", "live").strip(),
                instagram_login=env.get("INSTAGRAM_LOGIN", "instagram").strip(),
                instagram_user_id=env.get("INSTAGRAM_USER_ID", "").strip(),
                instagram_api_version=env.get("INSTAGRAM_API_VERSION", "").strip(),
                instagram_access_token=env.get("INSTAGRAM_ACCESS_TOKEN", "").strip(),
                instagram_share_to_feed=boolean("INSTAGRAM_SHARE_TO_FEED", True),
                api_timeout=float(env.get("INSTAGRAM_TIMEOUT", "30")),
                max_attempts=int(env.get("INSTAGRAM_MAX_ATTEMPTS", "3")),
                retry_base_seconds=float(env.get("INSTAGRAM_RETRY_BASE_SECONDS", "2")),
                retry_max_seconds=float(env.get("INSTAGRAM_RETRY_MAX_SECONDS", "60")),
                poll_interval_seconds=float(env.get("INSTAGRAM_POLL_INTERVAL_SECONDS", "60")),
                poll_attempts=int(env.get("INSTAGRAM_POLL_ATTEMPTS", "5")),
                s3_endpoint=env.get("S3_ENDPOINT", "").strip(), s3_bucket=env.get("S3_BUCKET", "").strip(),
                s3_access_key=env.get("S3_ACCESS_KEY", "").strip(), s3_secret_key=env.get("S3_SECRET_KEY", "").strip(),
                s3_region=env.get("S3_REGION", "us-east-1").strip(),
                s3_public_base_url=env.get("S3_PUBLIC_BASE_URL", "").strip().rstrip("/"),
                s3_presign_ttl_seconds=int(env.get("S3_PRESIGN_TTL_SECONDS", "7200")),
                s3_delete_after_publish=boolean("S3_DELETE_AFTER_PUBLISH", True),
                s3_addressing_style=env.get("S3_ADDRESSING_STYLE", "auto").strip(),
            )
        except ValueError:
            raise ValueError("Invalid publication configuration; check INSTAGRAM_*, S3_* and PIPELINE_MODE formats") from None
