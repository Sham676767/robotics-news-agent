from app.article_preview import render_html


def test_render_html_keeps_valid_source_image_and_link():
    rendered = render_html(
        "# Заголовок\n\n"
        "Вступление.\n\n"
        "## 1. Робот\n\n"
        "![Робот](<https://example.com/robot.jpg>)\n\n"
        "Описание новости.\n\n"
        "Источник: [Источник](https://example.com/story)\n"
    )

    assert '<img loading="lazy" src="https://example.com/robot.jpg" alt="Робот">' in rendered
    assert '<a href="https://example.com/story"' in rendered
    assert "<h2>1. Робот</h2>" in rendered


def test_render_html_rejects_non_web_image_url():
    rendered = render_html("![Неизвестно](<file:///tmp/image.jpg>)")

    assert "<img" not in rendered
