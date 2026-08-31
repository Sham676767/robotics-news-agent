import unittest

from app.article_editor import _attach_sources, validate_article


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
