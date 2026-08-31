import unittest

from app.fallback_article import generate_fallback_article


class FallbackArticleTests(unittest.TestCase):
    def setUp(self):
        self.top5 = [
            {
                "title": f"News {i}",
                "summary": f"Краткое описание новости {i}.",
                "source": f"Source {i}",
                "url": f"https://example.com/news-{i}",
                "topics": ["robotics"],
            }
            for i in range(1, 6)
        ]

    def test_fallback_returns_article_schema(self):
        article = generate_fallback_article(self.top5)

        self.assertEqual(len(article["items"]), 5)
        self.assertEqual(
            [item["card_index"] for item in article["items"]],
            [1, 2, 3, 4, 5],
        )
        self.assertTrue(all(set(item) == {"headline", "body", "card_index"} for item in article["items"]))

    def test_fallback_does_not_put_source_fields_inside_items(self):
        article = generate_fallback_article(self.top5)

        self.assertNotIn("url", article["items"][0])
        self.assertNotIn("source", article["items"][0])

    def test_fallback_requires_five_cards(self):
        with self.assertRaises(ValueError):
            generate_fallback_article(self.top5[:4])


if __name__ == "__main__":
    unittest.main()
