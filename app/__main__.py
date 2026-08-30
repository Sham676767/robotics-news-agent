from __future__ import annotations

import logging

from .collector import collect_all


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def main() -> None:
    items = collect_all()
    print(f"Collected {len(items)} news items")
    for item in items[:20]:
        print(f"- [{item.source}] {item.title}\n  {item.url}")


if __name__ == "__main__":
    main()
