from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class NewsItem:
    source: str
    title: str
    url: str
    published_at: datetime | None = None
    summary: str = ""
    language: str = ""
    topics: tuple[str, ...] = ()
    image_url: str | None = None

