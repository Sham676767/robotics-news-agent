from app.vk_draft import build_vk_draft


def _article():
    return {
        "title": "Тестовый выпуск",
        "intro": "Первое предложение. Второе предложение.",
        "items": [
            {
                "headline": f"Новость {index}",
                "body": "Первый факт. Второй факт. Третий факт.",
                "source": "Источник",
                "url": f"https://example.com/story-{index}",
                "image_url": (
                    f"https://images.example.com/{index}.jpg" if index in {1, 3, 5} else None
                ),
            }
            for index in range(1, 6)
        ],
    }


def test_vk_draft_is_explicitly_review_only():
    draft = build_vk_draft(_article())

    assert draft["status"] == "review_required"
    assert draft["publication_performed"] is False
    assert "Тестовый выпуск" in draft["message"]
    assert len(draft["image_sources"]) == 3
    assert [image["item_index"] for image in draft["image_sources"]] == [1, 3, 5]


def test_vk_draft_excludes_invalid_image_urls():
    article = _article()
    article["items"][0]["image_url"] = "file:///not-an-image.jpg"

    draft = build_vk_draft(article)

    assert [image["item_index"] for image in draft["image_sources"]] == [3, 5]
