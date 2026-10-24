"""Human-approved publication with durable checkpoints and duplicate protection."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Settings
from app.instagram_client import InstagramClient, InstagramError, PublishUncertain
from app.publishing_config import public_video_url
from app.reel_drafts import ReelDrafts, now_iso, read_json, write_json
from app.video_storage import S3VideoStorage, StorageError, VideoStorage

logger = logging.getLogger(__name__)


def publish_draft(reel_id: str, settings: Settings, *, dry_run: bool = False,
                  client: InstagramClient | None = None, storage: VideoStorage | None = None) -> dict[str, Any]:
    drafts = ReelDrafts(settings)
    config = settings.publishing

    def validate() -> tuple[Any, dict, dict]:
        folder, manifest, fingerprint = drafts.verify(reel_id)
        if manifest["mode"] != "live" or config.pipeline_mode == "stub":
            raise ValueError("Stub drafts cannot be published")
        state = read_json(folder / "state.json")
        approval = state.get("approval")
        if (not isinstance(approval, dict) or approval.get("bundle_sha256") != fingerprint
                or approval.get("account") != config.account
                or approval.get("share_to_feed") is not config.instagram_share_to_feed):
            raise ValueError("Approve this exact draft and Instagram account before publishing")
        return folder, manifest, state

    if dry_run:
        _, _, state = validate()
        return {"id": reel_id, "status": state["status"], "dry_run": True,
                "external_calls": [], "plan": ["quota", "upload_video", "create_reels_container", "poll", "media_publish", "optional_cleanup"]}

    with drafts.locked():
        folder, manifest, state = validate()
        config.require_account()
        config.require_storage()

        def save() -> None:
            write_json(folder / "state.json", state)

        def storage_identity() -> dict[str, str]:
            return {"endpoint": config.s3_endpoint, "bucket": config.s3_bucket}

        def cleanup() -> None:
            nonlocal storage
            record = state.get("storage")
            if not config.s3_delete_after_publish or not record or record.get("deleted"):
                return
            if record.get("identity") != storage_identity():
                state["cleanup_pending"] = True
                state["last_error"] = "storage_config_changed"
                save()
                return
            try:
                storage = storage if storage is not None else S3VideoStorage(config)
                storage.delete(record["key"])
                record["deleted"] = True
                state["cleanup_pending"] = False
                state["last_error"] = None
            except StorageError:
                state["cleanup_pending"] = True
                state["last_error"] = "storage_cleanup_failed"
                logger.warning("Publication succeeded; S3 cleanup remains pending")
            save()

        def success(media_id: str | None) -> dict[str, Any]:
            state.update(status="published", media_id=media_id, published_at=now_iso(), last_error=None)
            save()  # Record success BEFORE deleting the source object.
            cleanup()
            return {"id": reel_id, "status": "published", "media_id": state.get("media_id"),
                    "cleanup_pending": state.get("cleanup_pending", False)}

        if state["status"] == "published":
            cleanup()
            return {"id": reel_id, "status": "published", "media_id": state.get("media_id"),
                    "cleanup_pending": state.get("cleanup_pending", False)}
        if state["status"] not in {"approved", "uploading", "processing", "publishing", "publish_unknown"}:
            raise ValueError("Draft is not eligible for publication")
        if state.get("retry_not_before"):
            remaining = (datetime.fromisoformat(state["retry_not_before"]) - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                raise InstagramError("stored_rate_limit_wait_required", retry_after=remaining)
        client = client if client is not None else InstagramClient(config)
        try:
            # An interrupted media_publish may already have created the post.
            if state["status"] in {"publishing", "publish_unknown"}:
                if client.wait_ready(state["container_id"]) == "PUBLISHED":
                    return success(state.get("media_id"))
                state["status"] = "publish_unknown"
                save()
                raise PublishUncertain("inspect_account_before_any_manual_retry")
            client.check_quota()
            if not state.get("container_id"):
                key = f"reels/{reel_id}/{manifest['assets']['video.mp4']}.mp4"
                state.update(status="uploading", storage={"key": key, "identity": storage_identity(), "deleted": False})
                save()
                storage = storage if storage is not None else S3VideoStorage(config)
                stored = storage.upload(folder / "video.mp4", key)
                public_video_url(stored.url)
                if stored.expires_at is not None:
                    remaining = (stored.expires_at - datetime.now(timezone.utc)).total_seconds()
                    required = config.poll_interval_seconds * config.poll_attempts + config.api_timeout * config.max_attempts + 120
                    if remaining < required:
                        raise ValueError("Presigned video URL expires too soon; increase S3_PRESIGN_TTL_SECONDS")
                # Signed URLs are credentials; never persist or log them.
                caption = (folder / "caption.txt").read_text(encoding="utf-8").rstrip("\n")
                state["container_id"] = client.create_reel(stored.url, caption)
                state["status"] = "processing"
                save()
            result = client.wait_ready(state["container_id"])
            if result == "PUBLISHED":
                return success(state.get("media_id"))
            # May have waited several minutes; consult the account limit again before publishing.
            client.check_quota()
            state["status"] = "publishing"
            save()
            try:
                media_id = client.publish(state["container_id"])
            except PublishUncertain:
                state["status"] = "publish_unknown"
                save()
                raise
            except InstagramError:
                state["status"] = "processing"  # Explicit rejection; a later invocation may retry this container.
                save()
                raise
            return success(media_id)
        except InstagramError as exc:
            state["last_error"] = exc.reason
            if exc.retry_after is not None:
                state["retry_after_seconds"] = exc.retry_after
                state["retry_not_before"] = (datetime.now(timezone.utc) + timedelta(seconds=exc.retry_after)).isoformat()
            save()
            raise
        except (StorageError, ValueError):
            state["last_error"] = "storage_or_input_error"
            save()
            raise
