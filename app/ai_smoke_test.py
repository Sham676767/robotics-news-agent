from __future__ import annotations

from .ai_client import rank_with_gigachat
from .collector import collect_all
from .ranking import rank
from .relevance import filter_relevant


def main() -> None:
    items = filter_relevant(collect_all())
    ranked = rank(items, limit=10)
    candidates = [
        {
            "id": i,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "summary": item.summary,
            "topics": item.topics,
        }
        for i, item in enumerate(ranked, start=1)
    ]
    selected = rank_with_deepseek(candidates)
    print("GigaChat TOP-5:")
    for item in selected:
        print(item)


if __name__ == "__main__":
    main()
