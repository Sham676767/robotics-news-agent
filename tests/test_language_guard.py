import unittest

from app.language_guard import validate_russian_article


class RussianLanguageGuardTests(unittest.TestCase):
    def _article(self, body):
        return {
            "title": "Робототехника дня",
            "intro": "Это русское вступление о сегодняшних событиях. Здесь есть общий технологический контекст.",
            "items": [
                {"headline": f"Событие {i}", "body": body, "card_index": i}
                for i in range(1, 6)
            ],
        }

    def test_accepts_russian_prose_with_english_product_name(self):
        body = "Компания представила новый робот Atlas Pro. Разработка предназначена для складских задач. В карточке приведены конкретные сведения о проекте."
        validate_russian_article(self._article(body))

    def test_rejects_weekly_framing_in_daily_digest(self):
        article = self._article("Компания представила новый робот. Это описание события. Источник содержит факты.")
        article["title"] = "Дайджест за неделю в робототехнике"
        with self.assertRaises(ValueError):
            validate_russian_article(article)

    def test_rejects_predominantly_english_body(self):
        body = "The company announced a new humanoid robot. It is designed for warehouse tasks. The source provides additional technical details."
        with self.assertRaises(ValueError):
            validate_russian_article(self._article(body))

    def test_rejects_non_russian_intro(self):
        article = self._article("Компания представила новый робот. Это описание события. Источник содержит факты.")
        article["intro"] = "This is an English introduction about robotics. It summarizes the week."
        with self.assertRaises(ValueError):
            validate_russian_article(article)


if __name__ == "__main__":
    unittest.main()
