from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx

VK_API_ROOT = "https://api.vk.com/method"
DEFAULT_API_VERSION = "5.199"
DEFAULT_TIMEOUT = 20.0
MAX_SOURCE_IMAGES = 5
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class VKMediaError(RuntimeError):
    """Raised when a verified source image cannot become a VK attachment."""


def _api_version() -> str:
    return os.getenv("VK_API_VERSION", DEFAULT_API_VERSION)


def _timeout() -> float:
    return float(os.getenv("VK_PUBLISH_TIMEOUT", str(DEFAULT_TIMEOUT)))


def _valid_image_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return None


def _vk_call(
    client: Any, method: str, data: dict[str, Any], token: str
) -> dict[str, Any]:
    response = client.post(
        f"{VK_API_ROOT}/{method}",
        data={**data, "access_token": token, "v": _api_version()},
        timeout=_timeout(),
    )
    if response.status_code >= 400:
        raise VKMediaError(f"VK {method} HTTP {response.status_code}: {response.text[:500]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise VKMediaError(f"VK {method} returned a non-object response")
    if "error" in payload:
        error = payload["error"] or {}
        raise VKMediaError(
            f"VK {method} error {error.get('error_code')}: {error.get('error_msg')}"
        )
    response_data = payload.get("response")
    if not isinstance(response_data, dict) and not isinstance(response_data, list):
        raise VKMediaError(f"VK {method} returned an unexpected response")
    return payload


def _upload_one_image(
    client: Any, image_url: str, upload_url: str, token: str, group_id: str
) -> str:
    image_response = client.get(
        image_url,
        headers={"User-Agent": "Robotics News Agent/1.0", "Accept": "image/*"},
        follow_redirects=True,
        timeout=_timeout(),
    )
    if image_response.status_code >= 400:
        raise VKMediaError(
            f"Source image HTTP {image_response.status_code}: {image_url}"
        )
    content = image_response.content
    content_type = image_response.headers.get("content-type", "").split(";", 1)[0].lower()
    if not content_type.startswith("image/") or not content:
        raise VKMediaError(f"Source URL did not return an image: {image_url}")
    if len(content) > MAX_IMAGE_BYTES:
        raise VKMediaError(f"Source image is larger than {MAX_IMAGE_BYTES} bytes: {image_url}")

    upload_response = client.post(
        upload_url,
        files={"photo": ("source-image", content, content_type)},
        timeout=_timeout(),
    )
    if upload_response.status_code >= 400:
        raise VKMediaError(
            f"VK image upload HTTP {upload_response.status_code}: {upload_response.text[:500]}"
        )
    uploaded = upload_response.json()
    if not isinstance(uploaded, dict) or not all(
        uploaded.get(key) for key in ("photo", "server", "hash")
    ):
        raise VKMediaError("VK image upload returned incomplete data")

    saved = _vk_call(
        client,
        "photos.saveWallPhoto",
        {
            "group_id": group_id,
            "photo": uploaded["photo"],
            "server": uploaded["server"],
            "hash": uploaded["hash"],
        },
        token,
    )["response"]
    if not isinstance(saved, list) or not saved or not isinstance(saved[0], dict):
        raise VKMediaError("VK did not return a saved wall photo")
    photo = saved[0]
    owner_id = photo.get("owner_id")
    photo_id = photo.get("id")
    if not isinstance(owner_id, int) or not isinstance(photo_id, int):
        raise VKMediaError("VK saved photo does not contain owner_id and id")

    attachment = f"photo{owner_id}_{photo_id}"
    access_key = photo.get("access_key")
    if isinstance(access_key, str) and access_key:
        attachment += f"_{access_key}"
    return attachment


def upload_article_images(
    article: dict[str, Any],
    *,
    token: str,
    group_id: str,
    client: Any | None = None,
) -> list[str]:
    """Upload unique verified source images and return VK photo attachment IDs."""
    try:
        normalized_group_id = str(abs(int(group_id)))
    except (TypeError, ValueError) as exc:
        raise VKMediaError(f"VK_GROUP_ID must be an integer, got {group_id!r}") from exc

    image_urls: list[str] = []
    for item in article.get("items") or []:
        image_url = _valid_image_url(item.get("image_url"))
        if image_url and image_url not in image_urls:
            image_urls.append(image_url)
    image_urls = image_urls[:MAX_SOURCE_IMAGES]
    if not image_urls:
        return []

    owns_client = client is None
    active_client = client or httpx.Client()
    try:
        upload_server = _vk_call(
            active_client,
            "photos.getWallUploadServer",
            {"group_id": normalized_group_id},
            token,
        )["response"].get("upload_url")
        if not isinstance(upload_server, str) or not upload_server.startswith("https://"):
            raise VKMediaError("VK did not provide a secure wall-photo upload URL")

        attachments: list[str] = []
        failures: list[str] = []
        for image_url in image_urls:
            try:
                attachments.append(
                    _upload_one_image(
                        active_client, image_url, upload_server, token, normalized_group_id
                    )
                )
            except (VKMediaError, httpx.HTTPError, ValueError) as exc:
                failures.append(str(exc))

        if not attachments:
            details = "; ".join(failures[:3]) or "unknown image upload failure"
            raise VKMediaError(f"None of the source images could be attached: {details}")
        if failures:
            print(f"⚠️ VK attached {len(attachments)}/{len(image_urls)} source images")
        return attachments
    finally:
        if owns_client:
            active_client.close()
