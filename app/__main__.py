from __future__ import annotations

import logging

from .collector import collect_all
from .database import connect, save_items, count_items
from .relevance import filter_relevant


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def main() -> None:
    items = collect_all()
    relevant = filter_relevant(items)
    connection = connect()
    inserted, duplicates = save_items(connection, relevant)

    print(f"Collected: {len(items)}")
    print(f"Relevant: {len(relevant)}")
    print(f"Inserted: {inserted}")
    print(f"Duplicates: {duplicates}")
    print(f"Database total: {count_items(connection)}")

    for item in relevant[:20]:
        print(f"- [{item.source}] {item.title}\n  {item.url}")


if __name__ == "__main__":
    main()
