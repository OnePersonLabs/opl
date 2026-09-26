"""Hacker News story discovery via the public Algolia API."""

import datetime
import math
from typing import Any, Dict, List

import re

from . import http, log
from .query import extract_core_subject
from .relevance import token_overlap_relevance

# Common HN prefixes that can cause false-positive keyword matches
_HN_PREFIXES = re.compile(r"^(Tell HN|Show HN|Ask HN|Launch HN)\s*:\s*", re.IGNORECASE)

ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search"

DEPTH_CONFIG = {
    "quick": 15,
    "default": 30,
    "deep": 60,
}

MIN_STORY_POINTS = 2
HN_OVERFETCH_MULTIPLIER = 2

def _log(msg: str):
    log.source_log("HN", msg, tty_only=False)


def _date_to_unix(date_str: str) -> int:
    """Convert YYYY-MM-DD to Unix timestamp (start of day UTC)."""
    parts = date_str.split("-")
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    dt = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp())


def _unix_to_date(ts: int) -> str:
    """Convert Unix timestamp to YYYY-MM-DD."""
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d")


def search_hackernews(
    topic: str,
    from_date: str,
    to_date: str,
    depth: str = "default",
) -> Dict[str, Any]:
    """Search Hacker News via Algolia API.

    Args:
        topic: Search topic
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        depth: 'quick', 'default', or 'deep'

    Returns:
        Dict with Algolia response (contains 'hits' list).
    """
    count = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["default"])
    fetch_count = count * HN_OVERFETCH_MULTIPLIER
    from_ts = _date_to_unix(from_date)
    to_ts = _date_to_unix(to_date) + 86400  # Include the end date

    # Use extracted core subject instead of raw topic for cleaner Algolia matching
    core = extract_core_subject(topic)
    # Hyphens and commas tokenize awkwardly in Algolia; flatten them so themed
    # queries like "ts-bun-node" or "react, native tooling" become plain words.
    core_flat = _flatten_query_for_algolia(core)
    _log(f"Searching for '{core_flat}' (raw: '{topic}', since {from_date}, count={count})")

    # Use relevance-sorted search. The HN Algolia index only allows
    # `created_at_i` in numericFilters; `points` is NOT in its
    # `numericAttributesForFiltering`, so a `points>N` clause makes the API
    # return HTTP 400 ("invalid numeric attribute(points)") and zero stories.
    # Low-engagement stories are filtered client-side after overfetching so the
    # invalid numeric filter is not reintroduced.
    # NOTE: restrictSearchableAttributes=title omitted intentionally -- it would
    # miss Ask HN/Show HN threads where the topic appears in the body.
    params = {
        "query": core_flat,
        "tags": "story",
        "numericFilters": f"created_at_i>{from_ts},created_at_i<{to_ts}",
        "hitsPerPage": str(fetch_count),
    }
    # Algolia defaults to AND across query tokens, so a 4-5 word theme query
    # matches no stories. Mark all-but-the-first token as optional so Algolia
    # ranks by how many tokens match instead of requiring every one.
    tokens = core_flat.split()
    if len(tokens) > 1:
        params["optionalWords"] = " ".join(tokens[1:])

    from urllib.parse import urlencode
    url = f"{ALGOLIA_SEARCH_URL}?{urlencode(params)}"

    try:
        response = http.request("GET", url, timeout=30)
    except http.HTTPError as e:
        _log(f"Search failed: {e}")
        return {"hits": [], "error": str(e)}
    except Exception as e:
        _log(f"Search failed: {e}")
        return {"hits": [], "error": str(e)}

    raw_hits = response.get("hits", [])
    qualifying_hits = [
        hit for hit in raw_hits
        if (hit.get("points") or 0) > MIN_STORY_POINTS
    ]
    hits = qualifying_hits[:count]
    dropped_low_engagement = len(raw_hits) - len(qualifying_hits)
    if dropped_low_engagement:
        _log(f"Filtered {dropped_low_engagement}/{len(raw_hits)} low-engagement stories")
    if len(hits) != len(raw_hits):
        response = {**response, "hits": hits}
    _log(f"Found {len(hits)} stories")
    return response


_WORD_BOUNDARY_RE_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _flatten_query_for_algolia(text: str) -> str:
    """Normalise query for Algolia + post-filter comparison.

    Multi-keyword theme queries frequently contain commas (delimiters) or
    hyphens (compound terms like ``ts-bun-node``); both tokenize awkwardly.
    Flatten them to spaces and collapse runs of whitespace so the search
    parameter and the post-filter operate on the same shape.
    """
    return " ".join(text.replace(",", " ").replace("-", " ").split())


def _title_matches_query(title: str, query: str, author: str = "") -> bool:
    """Check if any query token appears as a whole word in the title.

    Returns True when the query is empty (no filter), or when at least one
    query token matches as a whole word in the title after stripping
    "Tell HN:", "Show HN:", "Ask HN:", "Launch HN:" prefixes.

    Any-word matching follows Algolia's `optionalWords` behavior. Token-overlap
    relevance scoring demotes hits where only one weak token matched.

    Word-boundary matching (rather than naive substring) prevents short
    tokens like ``ai`` or ``ts`` from matching unrelated words like
    ``email`` or ``artists``.
    """
    if not query:
        return True
    stripped = _HN_PREFIXES.sub("", title).strip()
    check_text = stripped.lower()
    # Normalise the query the same way search_hackernews does so post-filter
    # tokens line up with what Algolia actually saw.
    query_words = [w for w in _flatten_query_for_algolia(query.lower()).split() if w]
    if not query_words:
        return True
    for word in query_words:
        pattern = _WORD_BOUNDARY_RE_CACHE.get(word)
        if pattern is None:
            pattern = re.compile(rf"\b{re.escape(word)}\b")
            _WORD_BOUNDARY_RE_CACHE[word] = pattern
        if pattern.search(check_text):
            return True
    return False


def parse_hackernews_response(response: Dict[str, Any], query: str = "") -> List[Dict[str, Any]]:
    """Parse Algolia response into normalized item dicts.

    Args:
        response: Algolia search response
        query: Original search query for token-overlap relevance scoring

    Returns:
        List of item dicts ready for normalization.
    """
    hits = response.get("hits", [])
    # Post-filter: remove items where query only matched an HN prefix like "Tell HN:"
    if query:
        before = len(hits)
        hits = [
            h for h in hits
            if _title_matches_query(h.get("title", ""), query, h.get("author", ""))
        ]
        dropped = before - len(hits)
        if dropped:
            _log(f"Prefix filter removed {dropped}/{before} false-positive hits for '{query}'")
    items = []

    for i, hit in enumerate(hits):
        object_id = hit.get("objectID", "")
        points = hit.get("points") or 0
        num_comments = hit.get("num_comments") or 0
        created_at_i = hit.get("created_at_i")

        date_str = None
        if created_at_i:
            date_str = _unix_to_date(created_at_i)

        # Article URL vs HN discussion URL
        article_url = hit.get("url") or ""
        hn_url = f"https://news.ycombinator.com/item?id={object_id}"

        # Relevance: blend Algolia rank with token-overlap content matching
        rank_score = max(0.3, 1.0 - (i * 0.02))  # 1.0 -> 0.3 over 35 items
        engagement_boost = min(0.2, math.log1p(points) / 40)
        if query:
            content_score = token_overlap_relevance(query, hit.get("title", ""))
            relevance = min(1.0, 0.6 * rank_score + 0.4 * content_score + engagement_boost)
        else:
            relevance = min(1.0, rank_score * 0.7 + engagement_boost + 0.1)

        items.append({
            "id": object_id,
            "title": hit.get("title", ""),
            "url": article_url,
            "hn_url": hn_url,
            "author": hit.get("author", ""),
            "date": date_str,
            "engagement": {
                "points": points,
                "comments": num_comments,
            },
            "relevance": round(relevance, 2),
            "why_relevant": f"HN story about {hit.get('title', 'topic')[:60]}",
        })

    return items
