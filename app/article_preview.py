from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

OUTPUT_DIR = Path("articles")

_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(<(https?://[^>\s]+)>\)")
_SOURCE_RE = re.compile(r"^Источник:\s*\[([^\]]+)\]\((https?://[^)\s]+)\)$")
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.+)$")


def _safe_url(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return None


def render_html(markdown: str) -> str:
    """Render the generated Markdown into a lightweight local review page."""
    body: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            body.append(f"<p>{html.escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue

        image_match = _IMAGE_RE.fullmatch(line)
        if image_match:
            flush_paragraph()
            alt, url = image_match.groups()
            safe_url = _safe_url(url)
            if safe_url:
                body.append(
                    "<figure><img loading=\"lazy\" src=\""
                    + html.escape(safe_url, quote=True)
                    + "\" alt=\""
                    + html.escape(alt, quote=True)
                    + "\"></figure>"
                )
            continue

        heading_match = _HEADING_RE.fullmatch(line)
        if heading_match:
            flush_paragraph()
            level = "h1" if len(heading_match.group(1)) == 1 else "h2"
            body.append(f"<{level}>{html.escape(heading_match.group(2))}</{level}>")
            continue

        source_match = _SOURCE_RE.fullmatch(line)
        if source_match:
            flush_paragraph()
            source, url = source_match.groups()
            safe_url = _safe_url(url)
            if safe_url:
                body.append(
                    '<p class="source">Источник: <a href="'
                    + html.escape(safe_url, quote=True)
                    + '" rel="noopener noreferrer">'
                    + html.escape(source)
                    + "</a></p>"
                )
            continue

        paragraph.append(line)

    flush_paragraph()
    return """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Robotics News Agent — черновик</title>
<style>
body { max-width: 760px; margin: 0 auto; padding: 32px 18px 64px; font: 18px/1.6 system-ui, sans-serif; color: #172033; background: #f8fafc; }
article { background: #fff; padding: 34px; border-radius: 16px; box-shadow: 0 2px 14px #17203314; }
h1 { font-size: 1.7em; line-height: 1.22; margin: 0 0 .75em; }
h2 { font-size: 1.2em; line-height: 1.3; margin: 2em 0 .65em; }
p { margin: .7em 0; }
figure { margin: 1em 0; }
img { display: block; width: 100%; max-height: 480px; object-fit: cover; border-radius: 12px; background: #e5e7eb; }
.source { font-size: .88em; color: #526070; }
a { color: #155e9f; }
</style>
</head>
<body><article>
""" + "\n".join(body) + """
</article></body>
</html>
"""


def main() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    markdown_path = OUTPUT_DIR / f"{today}.md"
    if not markdown_path.exists():
        raise FileNotFoundError(f"Article draft not found: {markdown_path}")
    output_path = markdown_path.with_suffix(".html")
    output_path.write_text(render_html(markdown_path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Review page created: {output_path}")


if __name__ == "__main__":
    main()
