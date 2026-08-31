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

    def test_fallback_returns_renderable_article_schema(self):
        article = generate_fallback_article(self.top5)

        self.assertEqual(len(article["items"]), 5)
        self.assertEqual(
            [item["card_index"] for item in article["items"]],
            [1, 2, 3, 4, 5],
        )
        self.assertTrue(
            all(
                set(item) == {"headline", "body", "card_index", "source", "url"}
                for item in article["items"]
            )
        )

    def test_fallback_carries_source_metadata_from_cards(self):
        article = generate_fallback_article(self.top5)

        self.assertEqual(article["items"][0]["source"], "Source 1")
        self.assertEqual(article["items"][0]["url"], "https://example.com/news-1")
        self.assertEqual(article["items"][4]["source"], "Source 5")
        self.assertEqual(article["items"][4]["url"], "https://example.com/news-5")

    def test_fallback_requires_five_cards(self):
        with self.assertRaises(ValueError):
            generate_fallback_article(self.top5[:4])


if __name__ == "__main__":
    unittest.main()
