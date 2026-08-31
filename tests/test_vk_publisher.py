from app.vk_publisher import daily_random_id, render_vk_message


def test_render_vk_message_keeps_all_five_blocks_and_sources():
    article = {
        "title": "Тестовый дайджест",
        "intro": "Первое предложение. Второе предложение.",
        "items": [
            {
                "headline": f"Новость {i}",
                "body": "Факт первый. Факт второй. Факт третий.",
                "source": "Источник",
                "url": f"https://example.com/{i}",
            }
            for i in range(1, 6)
        ],
    }

    message = render_vk_message(article)

    assert message.startswith("Тестовый дайджест")
    for i in range(1, 6):
        assert f"{i}. Новость {i}" in message
        assert f"https://example.com/{i}" in message


def test_render_vk_message_is_not_markdown():
    article = {
        "title": "Заголовок",
        "intro": "Первое. Второе.",
        "items": [
            {
                "headline": "Новость",
                "body": "Один. Два. Три.",
                "source": "Источник",
                "url": "https://example.com/1",
            }
        ] * 5,
    }

    message = render_vk_message(article)
    assert "[" not in message
    assert "](" not in message


def test_daily_random_id_is_stable_for_reruns():
    article_a = {"title": "A", "intro": "B", "items": []}
    article_b = {"title": "Different", "intro": "Content", "items": []}

    assert daily_random_id(article_a) == daily_random_id(article_a)
    assert daily_random_id(article_a) == daily_random_id(article_b)
    assert 0 < daily_random_id(article_a) <= 0x7FFFFFFF
