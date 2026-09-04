from app.vk_media import upload_article_images


class _Response:
    def __init__(self, payload, *, status_code=200, content=b"", headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class _Client:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("get", url))
        return _Response(
            {},
            content=b"image-data",
            headers={"content-type": "image/jpeg"},
        )

    def post(self, url, **kwargs):
        self.calls.append(("post", url))
        if url.endswith("photos.getWallUploadServer"):
            return _Response({"response": {"upload_url": "https://upload.example.com/photo"}})
        if url == "https://upload.example.com/photo":
            return _Response({"photo": "serialized", "server": 12, "hash": "hash"})
        if url.endswith("photos.saveWallPhoto"):
            return _Response({"response": [{"owner_id": -123, "id": 456, "access_key": "key"}]})
        raise AssertionError(url)


def test_upload_article_images_returns_vk_attachment_ids():
    article = {
        "items": [
            {"image_url": "https://images.example.com/one.jpg"},
            {"image_url": "https://images.example.com/one.jpg"},
            {"image_url": "https://images.example.com/two.jpg"},
            {"image_url": None},
        ]
    }
    client = _Client()

    attachments = upload_article_images(
        article, token="token", group_id="123", client=client
    )

    assert attachments == ["photo-123_456_key", "photo-123_456_key"]
    assert client.calls.count(("post", "https://upload.example.com/photo")) == 2


def test_upload_article_images_skips_when_no_verified_images():
    client = _Client()

    attachments = upload_article_images(
        {"items": [{"image_url": None}, {"image_url": "file:///tmp/image.jpg"}]},
        token="token",
        group_id="123",
        client=client,
    )

    assert attachments == []
    assert client.calls == []
