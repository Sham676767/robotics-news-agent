"""Graph API Reels operations, bounded retries and resumable processing polls."""
from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.publishing_config import PublishingSettings, public_video_url

logger = logging.getLogger(__name__)


class InstagramError(RuntimeError):
    def __init__(self, reason: str, *, retry_after: float | None = None) -> None:
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(f"Instagram: {reason}")


class PublishUncertain(InstagramError):
    """A publish request may have succeeded: never blindly send it again."""


def graph_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise InstagramError("invalid_object_id")
    return value


def retry_after_seconds(value: str) -> float | None:
    try:
        result = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            result = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, result) if math.isfinite(result) else None


class InstagramClient:
    def __init__(self, settings: PublishingSettings, *, request: Callable[..., httpx.Response] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        settings.require_account()
        self.settings = settings
        self.request = request or httpx.request
        self.sleep = sleep

    def _request(self, method: str, path: str, *, params: dict[str, str] | None = None,
                 data: dict[str, str] | None = None, publishing: bool = False) -> dict[str, Any]:
        for attempt in range(self.settings.max_attempts):
            delay = min(self.settings.retry_max_seconds, self.settings.retry_base_seconds * 2 ** attempt)
            try:
                response = self.request(method, f"{self.settings.graph_base}/{path}",
                                        headers={"Authorization": f"Bearer {self.settings.instagram_access_token}"},
                                        params=params, data=data, timeout=self.settings.api_timeout,
                                        follow_redirects=False)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                reason = "connection_failed"
            except httpx.TransportError:
                if publishing:
                    raise PublishUncertain("publish_response_lost") from None
                reason = "transport_failed"
            else:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                error = payload.get("error") if isinstance(payload, dict) else None
                if 200 <= response.status_code < 300 and not error:
                    if not isinstance(payload, dict):
                        if publishing:
                            raise PublishUncertain("publish_response_invalid")
                        raise InstagramError("invalid_json_response")
                    return payload
                if 300 <= response.status_code < 400:
                    raise InstagramError("redirect_refused")
                code = error.get("code") if isinstance(error, dict) else None
                subcode = error.get("error_subcode") if isinstance(error, dict) else None
                # Auth, permission and integrity restrictions are never fixed by retrying.
                if code in (10, 190, 200) or response.status_code in (401, 403) or subcode == 2207051:
                    raise InstagramError("authorization_or_account_restriction")
                if code == 9 or subcode == 2207042:
                    raise InstagramError("publishing_quota_exhausted", retry_after=86400)
                if publishing and response.status_code >= 500:
                    raise PublishUncertain("publish_server_result_unknown")
                transient = (response.status_code == 429 or response.status_code >= 500
                             or code in (1, 2, 4, 17, 32, 613, 80002)
                             or (isinstance(error, dict) and error.get("is_transient") is True))
                if not transient:
                    raise InstagramError("request_rejected")
                minimum = retry_after_seconds(response.headers.get("Retry-After", ""))
                if minimum is not None:
                    if minimum > self.settings.retry_max_seconds:
                        raise InstagramError("rate_limit_wait_required", retry_after=minimum)
                    delay = max(delay, minimum)
                reason = "rate_limited" if response.status_code == 429 or code in (4, 17, 32, 613, 80002) else "temporary_error"
            if attempt + 1 == self.settings.max_attempts:
                raise InstagramError(reason, retry_after=delay)
            logger.warning("Instagram %s; attempt %d/%d after %.1fs", reason, attempt + 2, self.settings.max_attempts, delay)
            self.sleep(delay)
        raise InstagramError("attempts_exhausted")

    def check_quota(self) -> None:
        data = self._request("GET", f"{self.settings.instagram_user_id}/content_publishing_limit",
                             params={"fields": "quota_usage,config"})
        try:
            quota = data["data"][0]
            used, total = quota["quota_usage"], quota["config"]["quota_total"]
            if type(used) is not int or type(total) is not int or used < 0 or total < 1:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise InstagramError("invalid_quota_response") from None
        if used >= total:
            raise InstagramError("publishing_quota_exhausted", retry_after=86400)

    def create_reel(self, url: str, caption: str) -> str:
        public_video_url(url)
        data = self._request("POST", f"{self.settings.instagram_user_id}/media", data={
            "media_type": "REELS", "video_url": url, "caption": caption,
            "share_to_feed": str(self.settings.instagram_share_to_feed).lower(),
        })
        return graph_id(data.get("id"))

    def status(self, container_id: str) -> str:
        data = self._request("GET", graph_id(container_id), params={"fields": "status_code"})
        status = data.get("status_code")
        if status not in ("IN_PROGRESS", "FINISHED", "ERROR", "EXPIRED", "PUBLISHED"):
            raise InstagramError("unknown_container_status")
        return status

    def wait_ready(self, container_id: str) -> str:
        for attempt in range(self.settings.poll_attempts):
            status = self.status(container_id)
            if status in {"FINISHED", "PUBLISHED"}:
                return status
            if status in {"ERROR", "EXPIRED"}:
                raise InstagramError(f"container_{status.lower()}")
            if attempt + 1 < self.settings.poll_attempts:
                logger.info("Instagram processing; poll %d/%d", attempt + 1, self.settings.poll_attempts)
                self.sleep(self.settings.poll_interval_seconds)
        raise InstagramError("processing_pending")

    def publish(self, container_id: str) -> str:
        data = self._request("POST", f"{self.settings.instagram_user_id}/media_publish",
                             data={"creation_id": graph_id(container_id)}, publishing=True)
        try:
            return graph_id(data.get("id"))
        except InstagramError:
            raise PublishUncertain("publish_response_missing_media_id") from None
