from __future__ import annotations

from typing import List, Dict
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .ai_client import rank_with_deepseek
from .collector import collect_all
from .ranking import rank
from .relevance import classify, filter_relevant

OUTPUT_PATH = Path("data/latest_top5.json")

MAX_AGE = timedelta(days=7)
MAX_PER_SOURCE = 2
FRESH_TOPIC_WINDOW = timedelta(hours=72)
CORE_TOPICS = ("humanoid", "robot_dog", "exoskeleton", "robotics")
SPECIFIC_TOPICS = ("humanoid", "robot_dog", "exoskeleton")

EDITORIAL_REJECT_TERMS = (
    "top 10 stories", "top 10 robotics", "top 5 stories", "top 5 robotics",
    "best robotics stories", "robotics stories of", "month in review", "weekly roundup",
    "monthly roundup", "news roundup", "robotics roundup", "robotics news roundup",
    "what happened in", "this week in robotics", "this week's robotics news",
    "video friday", "weekly selection of awesome robotics videos",
)

LOW_VALUE_NEWS_TERMS = (
    "patent dispute", "patent lawsuit", "legal action against", "sues", "sued",
)
SPONSORED_REJECT_TERMS = (
    "brought to you by", "sponsored content", "advertisement", "advertorial",
)

# These stories discuss a sector or the research ecosystem rather than report a
# checkable robotics event. They are not useful daily TOP-5 entries when the
# card contains no launch, trial, study result, funding round, or deployment.
MARKET_DISCUSSION_REJECT_TERMS = (
    "next big profit machine", "next big profit", "promise of profits",
    "race for profits", "market opportunity", "market potential",
    "market trends", "market outlook", "industry outlook",
    "market discussion", "market commentary",
)
RESEARCH_META_REJECT_TERMS = (
    "paper deluge", "peer review", "research ecosystem",
    "research community", "publication growth", "future of peer review",
)

PROMO_REJECT_TERMS = (
    "discusses", "market hurdles", "market outlook", "market trends", "industry outlook",
    "joins us", "join us", "webinar", "fireside chat", "conference session",
    "conference panel", "panel discussion", "register now", "save your spot",
    "speakers include", "partner to encourage", "partnership to encourage",
    "platform to encourage", "platform for adoption", "initiative intended to help",
    "market discussion", "market analysis", "market commentary", "industry discussion",
    "thought leadership", "announces partnership", "partner on platform",
    "learn how", "learn why", "at robobusiness", "will discuss", "leaders will discuss",
    "apply now", "apply today", "applications open", "applications are open",
    "call for applications", "calling all robotics startups", "startup radar",
)

DUPLICATE_CONCEPT_GROUPS = (
    frozenset(("social expressiveness", "socially expressive", "expressive humanoid", "expressive behaviors", "expressive behaviour", "expressive conversation")),
    frozenset(("makes mistakes", "make mistakes", "makes errors", "make errors", "robot errors", "robot error", "awkward robot", "awkward robots", "robots are awkward")),
    frozenset(("become wary", "more suspicious", "trustworthy", "trust them", "human trust", "perceive robots")),
)

CONCRETE_EVENT_TERMS = (
    "launch", "launched", "unveil", "unveiled", "debut", "first", "deploy", "deployed",
    "deployment", "production", "mass production", "pilot", "contract", "funding", "raised",
    "investment", "acquisition", "order", "ships", "shipped", "delivered", "factory",
    "trial", "test", "tested", "demonstrates", "demonstrated", "prototype", "robot revealed",
)


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    query = "&".join(part for part in parsed.query.split("&") if part and not part.lower().startswith(("utm_", "fbclid=", "gclid=")))
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _dedupe(items: list) -> list:
    seen: set[str] = set()
    result = []
    for item in items:
        url = (item.url or "").strip()
        if not url:
            continue
        canonical = _canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        result.append(item)
    return result


def _recent_article_urls(
    article_dir: Path = Path("articles"),
    now: datetime | None = None,
) -> set[str]:
    """Return canonical source URLs from dated articles in the review window."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = (current - timedelta(days=14)).date()
    urls: set[str] = set()

    for path in article_dir.glob("*.md"):
        try:
            published_on = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not cutoff <= published_on <= current.date():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for url in re.findall(r"^Источник:\s*\[[^\]]+\]\((https?://[^)\s]+)\)\s*$", text, re.MULTILINE):
            urls.add(_canonical_url(url))
    return urls


def _exclude_recently_published(items: list, article_dir: Path = Path("articles"), now: datetime | None = None) -> list:
    recent_urls = _recent_article_urls(article_dir, now)
    return [item for item in items if _canonical_url(item.url) not in recent_urls]


def _is_editorial_roundup(item) -> bool:
    text = f"{item.title} {item.summary}".lower()
    return (
        any(term in text for term in EDITORIAL_REJECT_TERMS)
        or any(term in text for term in LOW_VALUE_NEWS_TERMS)
        or any(term in text for term in SPONSORED_REJECT_TERMS)
    )


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _is_promotional(item) -> bool:
    title = re.sub(r"\s+", " ", item.title.lower()).strip()
    summary = re.sub(r"\s+", " ", item.summary.lower()).strip()
    combined = f"{title} {summary}"
    promo_hits = sum(1 for term in PROMO_REJECT_TERMS if _contains_term(combined, term))
    concrete_hits = sum(1 for term in CONCRETE_EVENT_TERMS if _contains_term(combined, term))
    partnership_or_platform = any(term in combined for term in ("partner", "partnership", "platform", "initiative"))
    market_meta = any(term in combined for term in ("market", "industry", "adoption", "discussion", "outlook"))
    return promo_hits >= 2 or (promo_hits >= 1 and concrete_hits == 0) or (partnership_or_platform and market_meta and concrete_hits == 0)


def _is_low_specificity_discussion(item) -> bool:
    combined = re.sub(r"\s+", " ", f"{item.title} {item.summary}".lower()).strip()
    concrete_hits = sum(1 for term in CONCRETE_EVENT_TERMS if _contains_term(combined, term))
    market_discussion = any(_contains_term(combined, term) for term in MARKET_DISCUSSION_REJECT_TERMS)
    research_meta = any(_contains_term(combined, term) for term in RESEARCH_META_REJECT_TERMS)
    return (market_discussion or research_meta) and concrete_hits == 0


def _is_aggregator(item) -> bool:
    return item.source.lower().startswith("google news")


def _filter_editorial(items: list) -> list:
    filtered = [
        item for item in items
        if not _is_editorial_roundup(item)
        and not _is_promotional(item)
        and not _is_low_specificity_discussion(item)
    ]
    # An aggregated headline is only a reserve candidate. Do not exclude it
    # outright: a thin news day must still be able to produce five genuine
    # articles, but prefer direct publishers whenever five are available.
    direct = [item for item in filtered if not _is_aggregator(item)]
    return direct if len(direct) >= 5 else filtered


def _recent(items: list) -> list:
    now = datetime.now(timezone.utc)
    result = []
    for item in items:
        published_at = item.published_at
        if not published_at:
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        age = now - published_at
        if timedelta(0) <= age <= MAX_AGE:
            result.append(item)
    return result


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9а-яё]{4,}", text.lower())
    stop = {"robot", "robots", "robotics", "humanoid", "humanoids", "study", "new", "news", "research", "when", "with", "from", "that", "this", "into", "about", "their", "they", "have", "more", "than", "people", "robot's"}
    return {word for word in words if word not in stop}


def _duplicate_concepts(item) -> set[int]:
    text = f"{item.title} {item.summary}".lower()
    return {index for index, phrases in enumerate(DUPLICATE_CONCEPT_GROUPS) if any(phrase in text for phrase in phrases)}


def _near_duplicate(a, b) -> bool:
    concepts_a, concepts_b = _duplicate_concepts(a), _duplicate_concepts(b)
    # Different publishers commonly paraphrase this study as social
    # expressiveness + mistakes + trust/wary/suspicious. Token overlap alone
    # misses those inflection and wording changes.
    if len(concepts_a & concepts_b) >= 2 and (len(concepts_a) >= 2 or len(concepts_b) >= 2):
        return True

    title_a, title_b = _tokens(a.title), _tokens(b.title)
    if not title_a or not title_b:
        return False
    title_overlap = len(title_a & title_b) / max(1, min(len(title_a), len(title_b)))
    if title_overlap < 0.45:
        return False
    summary_a, summary_b = _tokens(a.summary), _tokens(b.summary)
    if not summary_a or not summary_b:
        return title_overlap >= 0.70
    summary_overlap = len(summary_a & summary_b) / max(1, min(len(summary_a), len(summary_b)))
    return title_overlap >= 0.45 and summary_overlap >= 0.12


def _diverse_ranked(items: list, limit: int = 12) -> list:
    ranked = rank(items, limit=max(limit * 3, 20))
    result = []
    per_source: dict[str, int] = {}
    covered_specific: set[str] = set()
    for item in ranked:
        if len(result) >= limit:
            break
        if per_source.get(item.source, 0) >= MAX_PER_SOURCE:
            continue
        if any(_near_duplicate(item, existing) for existing in result):
            continue
        topics = set(classify(item))
        new_specific = topics.intersection(SPECIFIC_TOPICS) - covered_specific
        if not new_specific:
            continue
        result.append(item)
        per_source[item.source] = per_source.get(item.source, 0) + 1
        covered_specific.update(new_specific)

    selected_urls = {_canonical_url(item.url) for item in result}
    for item in ranked:
        if len(result) >= limit:
            break
        canonical = _canonical_url(item.url)
        if canonical in selected_urls or any(_near_duplicate(item, existing) for existing in result):
            continue
        if per_source.get(item.source, 0) >= MAX_PER_SOURCE:
            continue
        result.append(item)
        per_source[item.source] = per_source.get(item.source, 0) + 1
        selected_urls.add(canonical)
    return result


def build_candidates(limit: int = 12, items: list | None = None) -> list[dict]:
    collected = items if items is not None else collect_all()
    relevant = filter_relevant(collected)
    editorial = _filter_editorial(relevant)
    recent = _exclude_recently_published(_dedupe(_recent(editorial)))
    if len(recent) < 5:
        raise RuntimeError(f"Only {len(recent)} unique relevant stories are newer than {MAX_AGE.days} days; refusing to publish stale or duplicate news")
    ranked = _diverse_ranked(recent, limit=limit)
    if len(ranked) < 5:
        raise RuntimeError(f"Only {len(ranked)} unique candidates remain after source/topic diversity filtering; expected at least 5")
    return [{"id": index, "title": item.title, "source": item.source, "url": item.url, "published_at": item.published_at.isoformat() if item.published_at else None, "summary": item.summary[:1500], "topics": classify(item)} for index, item in enumerate(ranked, start=1)]


def _topic_set(item: dict) -> set[str]:
    return set(item.get("topics") or ())


def _is_fresh_candidate(item: dict) -> bool:
    value = item.get("published_at")
    if not value:
        return False
    try:
        published_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return timedelta(0) <= datetime.now(timezone.utc) - published_at <= FRESH_TOPIC_WINDOW


def _pick_result(candidate: dict, choice: dict | None = None, reason: str = "") -> dict:
    return {"rank": 0, "id": candidate["id"], "title": candidate["title"], "source": candidate["source"], "url": candidate["url"], "published_at": candidate["published_at"], "summary": candidate["summary"], "topics": candidate["topics"], "ai_score": choice.get("score") if choice else None, "why_selected": (choice.get("reason", "") if choice else reason)}


def _freshness_priority(candidate: dict) -> int:
    value = candidate.get("published_at")
    if not value:
        return 0
    try:
        published_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - published_at
    if timedelta(0) <= age <= FRESH_TOPIC_WINDOW:
        return 3
    if age <= timedelta(hours=120):
        return 2
    if age <= MAX_AGE:
        return 1
    return 0


def _score_coverage(candidate: dict, choice: dict, covered_topics: set[str], used_sources: set[str]) -> tuple[float, ...]:
    topics = _topic_set(candidate)
    return (
        float(len(topics.intersection(SPECIFIC_TOPICS) - covered_topics)),
        float(len(topics.intersection(CORE_TOPICS) - covered_topics)),
        float(_freshness_priority(candidate)),
        float(candidate["source"] not in used_sources),
        float(choice.get("score") or 0),
    )


def _best_coverage_choice(choices, covered_topics, used_ids, used_sources):
    eligible = [pair for pair in choices if pair[1]["id"] not in used_ids]
    return max(eligible, key=lambda pair: _score_coverage(pair[1], pair[0], covered_topics, used_sources)) if eligible else None


def _best_ranked_fill(choices, covered_topics, used_ids, used_sources):
    eligible = []
    for choice, candidate in choices:
        if candidate["id"] in used_ids:
            continue
        eligible.append((choice, candidate, candidate["source"] not in used_sources, _topic_set(candidate) - covered_topics))
    return max(
        eligible,
        key=lambda row: (
            _freshness_priority(row[1]),
            float(row[0].get("score") or 0),
            row[2],
            len(row[3]),
        ),
    )[:2] if eligible else None


def select_top5(news=None) -> List[Dict]:
    candidates = build_candidates(items=news)
    selected = rank_with_deepseek(candidates, limit=len(candidates))
    by_id = {item["id"]: item for item in candidates}
    valid_choices = []
    for choice in selected:
        try:
            candidate = by_id.get(int(choice["id"]))
        except (KeyError, TypeError, ValueError):
            candidate = None
        if candidate:
            valid_choices.append((choice, candidate))

    result, used_sources, covered_topics, chosen_ids = [], set(), set(), set()
    # Topic variety should never force an old story above a fresh event. Only
    # seek coverage for pillars that actually have a candidate from the last
    # 72 hours; older stories remain available as reserve fill.
    target_topics = set().union(*(
        _topic_set(candidate).intersection(SPECIFIC_TOPICS)
        for candidate in candidates
        if _is_fresh_candidate(candidate)
    )) if candidates else set()
    while len(result) < 5 and not target_topics.issubset(covered_topics):
        picked = _best_coverage_choice(valid_choices, covered_topics, chosen_ids, used_sources)
        if not picked:
            break
        choice, candidate = picked
        new_specific = _topic_set(candidate).intersection(SPECIFIC_TOPICS) - covered_topics
        if not new_specific:
            break
        result.append(_pick_result(candidate, choice))
        chosen_ids.add(candidate["id"]); used_sources.add(candidate["source"]); covered_topics.update(_topic_set(candidate))

    while len(result) < 5:
        picked = _best_ranked_fill(valid_choices, covered_topics, chosen_ids, used_sources)
        if not picked:
            break
        choice, candidate = picked
        result.append(_pick_result(candidate, choice))
        chosen_ids.add(candidate["id"]); used_sources.add(candidate["source"]); covered_topics.update(_topic_set(candidate))

    if len(result) < 5:
        for candidate in candidates:
            if candidate["id"] in chosen_ids:
                continue
            result.append(_pick_result(candidate, reason="Deterministic fallback from ranked candidates")); chosen_ids.add(candidate["id"])
            if len(result) >= 5:
                break
    if len(result) < 5:
        raise RuntimeError(f"Only {len(result)} usable stories available; expected 5")
    for index, item in enumerate(result[:5], start=1):
        item["rank"] = index
    return result[:5]


def main() -> None:
    selected = select_top5()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Selected {len(selected)} stories")


if __name__ == "__main__":
    main()
