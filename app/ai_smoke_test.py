from __future__ import annotations

from .ai_client import rank_with_deepseek
from .collector import collect_all
from .ranking import rank_items
from .relevance import filter_relevant


def main() -> None:
    items = filter_relevant(collect_all())
    ranked = rank_items(items)
    candidates = [
        {
            "id": i,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "summary": item.summary,
            "topics": item.topics,
        }
        for i, item in enumerate(ranked[:10], start=1)
    ]
    selected = rank_with_deepseek(candidates)
    print("DeepSeek TOP-5:")
    for item in selected:
        print(item)


if __name__ == "__main__":
    main()
