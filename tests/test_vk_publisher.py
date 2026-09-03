from app.vk_publisher import daily_random_id, render_vk_message


def _article():
    return {
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


def test_render_vk_message_keeps_all_five_blocks_and_sources():
    message = render_vk_message(_article())

    assert message.startswith("🤖 РОБОТОТЕХНИКА — ДАЙДЖЕСТ ДНЯ")
    assert "Тестовый дайджест" in message
    for i, icon in enumerate(("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"), start=1):
        assert f"{icon} Новость {i}" in message
        assert f"🔗 Источник: Источник" in message
        assert f"https://example.com/{i}" in message


def test_render_vk_message_does_not_use_long_visual_separators():
    message = render_vk_message(_article())
    assert "━━━━━━━━━━━━━━━━━━━━" not in message
    assert message.count("\n—\n") == 1


def test_render_vk_message_is_plain_readable_text():
    message = render_vk_message(_article())
    assert "[" not in message
    assert "](" not in message
    assert "РОБОТОТЕХНИКА — ДАЙДЖЕСТ ДНЯ" in message
    assert message.endswith("🤖 Пять событий дня без рекламных обещаний и неподтверждённых выводов.")


def test_daily_random_id_is_stable_for_reruns():
    article_a = {"title": "A", "intro": "B", "items": []}
    article_b = {"title": "Different", "intro": "Content", "items": []}

    assert daily_random_id(article_a) == daily_random_id(article_a)
    assert daily_random_id(article_a) == daily_random_id(article_b)
    assert 0 < daily_random_id(article_a) <= 0x7FFFFFFF
