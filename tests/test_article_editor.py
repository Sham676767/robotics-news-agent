import json
import os
import unittest
from unittest.mock import Mock, patch

from app.article_editor import (
    SYSTEM_PROMPT,
    _attach_sources,
    _is_parseable_article_json,
    _normalize_article,
    _request_openrouter,
    generate_article,
    validate_article,
)


class ArticleEditorTests(unittest.TestCase):
    def setUp(self):
        self.top5 = [
            {
                "title": f"News {i}",
                "source": f"Source {i}",
                "url": f"https://example.com/news-{i}",
            }
            for i in range(1, 6)
        ]

    def valid_article(self):
        return {
            "title": "Робототехника недели",
            "intro": "Первая новость показывает развитие робототехники. Вторая новость показывает другой сегмент рынка.",
            "items": [
                {
                    "headline": f"Событие {i}",
                    "body": "Это первое предложение блока. Это второе предложение блока. Это третье предложение блока.",
                    "card_index": i,
                }
                for i in range(1, 6)
            ],
        }

    def test_system_prompt_is_for_a_daily_digest(self):
        self.assertIn("ежедневный аналитический дайджест", SYSTEM_PROMPT)
        self.assertIn("общую картину ДНЯ", SYSTEM_PROMPT)
        self.assertIn("всего выпуска за день", SYSTEM_PROMPT)
        self.assertNotIn("еженедельный аналитический дайджест", SYSTEM_PROMPT)
        self.assertNotIn("общую картину недели", SYSTEM_PROMPT)

    def test_json_response_guard_rejects_safety_message(self):
        self.assertFalse(_is_parseable_article_json("User Safety: safe"))
        self.assertFalse(_is_parseable_article_json("Let me think through this first."))
        self.assertTrue(_is_parseable_article_json('{"title": "Черновик"}'))

    @patch("app.article_editor.time.sleep")
    @patch("app.article_editor.httpx.post")
    def test_request_retries_non_json_provider_response(self, post, sleep):
        invalid_response = Mock()
        invalid_response.status_code = 200
        invalid_response.json.return_value = {
            "choices": [{"message": {"content": "User Safety: safe"}}],
        }
        valid_response = Mock()
        valid_response.status_code = 200
        valid_response.json.return_value = {
            "choices": [{"message": {"content": '{"title": "Черновик"}'}}],
        }
        post.side_effect = [invalid_response, valid_response]

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_MAX_ATTEMPTS": "2",
                "OPENROUTER_RETRY_BASE_SECONDS": "0",
                "OPENROUTER_RETRY_MAX_SECONDS": "0",
            },
            clear=False,
        ):
            content = _request_openrouter({}, {})

        self.assertEqual(content, '{"title": "Черновик"}')
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.0)

    @patch("app.article_editor._request_openrouter")
    def test_generate_article_uses_second_repair_attempt(self, request):
        top5 = [
            {
                "title": f"News {i}",
                "summary": f"Source card {i}",
                "source": f"Source {i}",
                "url": f"https://example.com/news-{i}",
            }
            for i in range(1, 6)
        ]
        invalid = {
            "title": "Робототехника дня",
            "intro": "Сегодня есть новости о роботах. Карточки содержат факты.",
            "items": [
                {"headline": "Новость", "body": "Слишком короткий блок."}
                for _ in range(5)
            ],
        }
        valid = {
            "title": "Робототехника дня",
            "intro": "Сегодня есть новости о роботах. Карточки содержат факты.",
            "items": [
                {
                    "headline": "Новость",
                    "body": "Первый факт указан в карточке. Второй факт не добавляет деталей. Третий факт сохраняет осторожную формулировку.",
                }
                for _ in range(5)
            ],
        }
        request.side_effect = [
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(valid, ensure_ascii=False),
        ]

        article = generate_article(top5, api_key="test-key")

        self.assertEqual(request.call_count, 3)
        self.assertEqual(len(article["items"]), 5)


    def test_normalize_article_assigns_indexes_by_position(self):
        article = self.valid_article()
        for item in article["items"]:
            item.pop("card_index")

        normalized = _normalize_article(article)
        self.assertEqual(
            [item["card_index"] for item in normalized["items"]],
            [1, 2, 3, 4, 5],
        )

    def test_normalize_article_overwrites_ai_indexes(self):
        article = self.valid_article()
        for i, item in enumerate(article["items"], start=1):
            item["card_index"] = 6 - i

        normalized = _normalize_article(article)
        self.assertEqual(
            [item["card_index"] for item in normalized["items"]],
            [1, 2, 3, 4, 5],
        )

    def test_validate_accepts_correct_five_card_article(self):
        validate_article(self.valid_article(), self.top5)

    def test_validate_rejects_wrong_card_order(self):
        article = self.valid_article()
        article["items"][0]["card_index"] = 2
        with self.assertRaises(ValueError):
            validate_article(article, self.top5)

    def test_validate_rejects_wrong_item_count(self):
        article = self.valid_article()
        article["items"] = article["items"][:4]
        with self.assertRaises(ValueError):
            validate_article(article, self.top5)

    def test_validate_rejects_wrong_body_length(self):
        article = self.valid_article()
        article["items"][0]["body"] = "Слишком коротко."
        with self.assertRaises(ValueError):
            validate_article(article, self.top5)

    def test_validate_rejects_invalid_source_url(self):
        top5 = list(self.top5)
        top5[0] = dict(top5[0], url="not-a-url")
        with self.assertRaises(ValueError):
            validate_article(self.valid_article(), top5)

    def test_attach_sources_uses_card_index_not_ai_urls(self):
        article = self.valid_article()
        attached = _attach_sources(article, self.top5)

        self.assertEqual(attached["items"][0]["source"], "Source 1")
        self.assertEqual(attached["items"][0]["url"], "https://example.com/news-1")
        self.assertEqual(attached["items"][4]["source"], "Source 5")
        self.assertEqual(attached["items"][4]["url"], "https://example.com/news-5")

    def test_attach_sources_preserves_one_source_per_card(self):
        article = self.valid_article()
        attached = _attach_sources(article, self.top5)
        urls = [item["url"] for item in attached["items"]]
        self.assertEqual(urls, [f"https://example.com/news-{i}" for i in range(1, 6)])
        self.assertEqual(len(urls), len(set(urls)))


if __name__ == "__main__":
    unittest.main()
