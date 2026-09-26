"""Reusable local scoring signals for pipeline stages."""

from __future__ import annotations

import math

from . import dates, relevance, schema

# Editorial signal-to-noise scores. Grounding (Google Search) is 1.0 baseline;
# social platforms discounted for noise.
SOURCE_QUALITY = {
    "hackernews": 0.8,
    "youtube": 0.85,
    "reddit": 0.6,
    "x": 0.68,
    "polymarket": 0.5,
    "tiktok": 0.58,
}


def source_quality(source: str) -> float:
    return SOURCE_QUALITY.get(source, 0.6)


def local_relevance(
    item: schema.SourceItem,
    ranking_query: "str | relevance.PreparedQuery",
) -> float:
    text = "\n".join(
        part
        for part in [item.title, item.body, item.snippet]
        if part
    )
    hashtags = item.metadata.get("hashtags") if isinstance(item.metadata, dict) else None
    score = relevance.token_overlap_relevance(ranking_query, text, hashtags=hashtags)

    # High-engagement YouTube floor: official videos with millions of views
    # often have titles that don't keyword-match the query (e.g., "YE - FATHER
    # (feat. TRAVIS SCOTT)" doesn't match "kanye west"). The engagement signals
    # say "this is important" even when text overlap is weak.
    if item.source == "youtube" and item.engagement.get("views", 0) > 100_000:
        score = max(score, 0.3)

    # Project-mode GitHub floor: items fetched via --github-repo are explicitly
    # requested by the user and relevant by construction. Without this floor,
    # Repositories with low token diversity (for example, "acme/acme").
    # get pruned despite being the primary search target.
    labels = item.metadata.get("labels", []) if isinstance(item.metadata, dict) else []
    if "project-mode" in labels:
        score = max(score, 0.8)

    return score


def freshness(
    item: schema.SourceItem,
    freshness_mode: str = "balanced_recent",
    *,
    reference_date: str | None = None,
    max_days: int = 30,
) -> int:
    score = dates.recency_score(
        item.published_at,
        max_days=max_days,
        reference_date=reference_date,
    )
    if freshness_mode == "strict_recent":
        return int(score)
    if freshness_mode == "evergreen_ok":
        return int((score * 0.6) + 40)
    return int((score * 0.8) + 10)


def log1p_safe(value: float | int | None) -> float:
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric <= 0:
        return 0.0
    return math.log1p(numeric)


def _top_comment_score(item: schema.SourceItem) -> float:
    comments = item.metadata.get("top_comments") or []
    if not comments or not isinstance(comments[0], dict):
        return 0.0
    return log1p_safe(comments[0].get("score"))


# Per-platform log-reference for normalizing a top comment's vote count into a
# [0,1] signal. Reddit upvotes run in the hundreds-to-thousands; YouTube/TikTok
# likes run 10-600x higher (and the top end is display-abbreviated: "39K" is
# stored as 39000). A raw or single-scale log compare would let YouTube/TikTok
# dominate purely by platform scale. Each value is the
# log1p of a "very high" top-comment count for that platform, so dividing a
# comment's log1p(score) by it yields a comparable cross-platform strength.
_VOTE_LOG_REFERENCE: dict[str, float] = {
    "reddit":     7.6,   # ~log1p(2000)
    "hackernews": 6.2,   # ~log1p(500)
    "youtube":    10.3,  # ~log1p(30000)
    "tiktok":     10.3,  # ~log1p(30000)
    "x":          9.2,   # ~log1p(10000)
}
_VOTE_LOG_REFERENCE_DEFAULT = 7.6


def normalized_comment_vote(source: str, score: "float | int | None") -> float:
    """Normalize a single comment's vote count to [0,1] within its platform.

    Per-platform references make large TikTok and Reddit comment counts
    comparable for the cross-candidate community-comment block.
    """
    base = log1p_safe(score)
    if base <= 0.0:
        return 0.0
    ref = _VOTE_LOG_REFERENCE.get(source, _VOTE_LOG_REFERENCE_DEFAULT)
    return max(0.0, min(1.0, base / ref))


# Per-source engagement weights: list of (field_name, weight) tuples.
# Reddit, YouTube, and TikTok use custom functions because they include
# a dedicated 10% top-comment-score slot (see _reddit_engagement,
# _youtube_engagement, _tiktok_engagement).
ENGAGEMENT_WEIGHTS: dict[str, list[tuple[str, float]]] = {
    "x":            [("likes", 0.55), ("reposts", 0.25), ("replies", 0.15), ("quotes", 0.05)],
    "hackernews":   [("points", 0.55), ("comments", 0.45)],
    "polymarket":   [("volume", 0.60), ("liquidity", 0.40)],
}


def _weighted_engagement(item: schema.SourceItem, weights: list[tuple[str, float]]) -> float | None:
    values = [(log1p_safe(item.engagement.get(field)), weight) for field, weight in weights]
    if not any(v for v, _ in values):
        return None
    return sum(v * w for v, w in values)


def _reddit_engagement(item: schema.SourceItem) -> float | None:
    score = log1p_safe(item.engagement.get("score"))
    comments = log1p_safe(item.engagement.get("num_comments"))
    ratio = float(item.engagement.get("upvote_ratio") or 0.0)
    top_comment = _top_comment_score(item)
    if not any([score, comments, ratio, top_comment]):
        return None
    return (0.50 * score) + (0.35 * comments) + (0.05 * (ratio * 10.0)) + (0.10 * top_comment)


def _youtube_engagement(item: schema.SourceItem) -> float | None:
    views = log1p_safe(item.engagement.get("views"))
    likes = log1p_safe(item.engagement.get("likes"))
    comments = log1p_safe(item.engagement.get("comments"))
    top_comment = _top_comment_score(item)
    if not any([views, likes, comments, top_comment]):
        return None
    # Keep views dominant while reserving 10% for the top-comment signal.
    return (0.45 * views) + (0.32 * likes) + (0.13 * comments) + (0.10 * top_comment)


def _tiktok_engagement(item: schema.SourceItem) -> float | None:
    views = log1p_safe(item.engagement.get("views"))
    likes = log1p_safe(item.engagement.get("likes"))
    comments = log1p_safe(item.engagement.get("comments"))
    top_comment = _top_comment_score(item)
    if not any([views, likes, comments, top_comment]):
        return None
    return (0.45 * views) + (0.27 * likes) + (0.18 * comments) + (0.10 * top_comment)


def _generic_engagement(item: schema.SourceItem) -> float | None:
    if not item.engagement:
        return None
    values = [logged for v in item.engagement.values() if (logged := log1p_safe(v)) > 0]
    if not values:
        return None
    return sum(values) / len(values)


def engagement_raw(item: schema.SourceItem) -> float | None:
    if item.source == "reddit":
        return _reddit_engagement(item)
    if item.source == "youtube":
        return _youtube_engagement(item)
    if item.source == "tiktok":
        return _tiktok_engagement(item)
    weights = ENGAGEMENT_WEIGHTS.get(item.source)
    if weights:
        return _weighted_engagement(item, weights)
    return _generic_engagement(item)


def normalize(values: list[float | None]) -> list[int | None]:
    valid = [value for value in values if value is not None]
    if not valid:
        return [None for _ in values]
    low = min(valid)
    high = max(valid)
    if math.isclose(low, high):
        return [50 if value is not None else None for value in values]
    return [
        None
        if value is None
        else int(((value - low) / (high - low)) * 100)
        for value in values
    ]


def annotate_stream(
    items: list[schema.SourceItem],
    ranking_query: "str | relevance.PreparedQuery",
    freshness_mode: str,
    reference_date: str | None = None,
    max_days: int = 30,
) -> list[schema.SourceItem]:
    """Attach local scoring metadata and return items sorted by local_rank_score."""
    prepared_query = ranking_query if isinstance(ranking_query, relevance.PreparedQuery) else relevance.PreparedQuery(ranking_query)
    engagement_scores = normalize([engagement_raw(item) for item in items])
    for item, eng_score in zip(items, engagement_scores, strict=True):
        item.local_relevance = local_relevance(item, prepared_query)
        item.freshness = freshness(
            item,
            freshness_mode,
            reference_date=reference_date,
            max_days=max_days,
        )
        item.engagement_score = eng_score
        item.source_quality = source_quality(item.source)
        item.local_rank_score = (
            0.65 * item.local_relevance
            + 0.25 * (item.freshness / 100.0)
            + 0.10 * ((eng_score or 0) / 100.0)
        )
    return sorted(items, key=lambda item: item.local_rank_score or 0, reverse=True)


_SOCIAL_SOURCES = {"reddit", "x", "tiktok"}

# Minimum view count for short-video platforms. Items below this floor
# are typically spam reposts or low-effort clips that add no unique signal.
_VIDEO_ENGAGEMENT_FLOOR_SOURCES = {"tiktok"}
_VIDEO_ENGAGEMENT_FLOOR_VIEWS = 1000


def _passes_engagement_floor(item: schema.SourceItem, sole_source: bool) -> bool:
    """Check whether a TikTok item meets the minimum view floor.

    Items from sources not in _VIDEO_ENGAGEMENT_FLOOR_SOURCES always pass.
    If the item's source is the *only* source represented in the batch
    (sole_source=True), all items pass so we never return an empty result
    for a whole source.
    """
    if item.source not in _VIDEO_ENGAGEMENT_FLOOR_SOURCES:
        return True
    if sole_source:
        return True
    views = item.engagement.get("views", 0) if item.engagement else 0
    return views >= _VIDEO_ENGAGEMENT_FLOOR_VIEWS


def prune_low_relevance(
    items: list[schema.SourceItem],
    minimum: float = 0.15,
) -> list[schema.SourceItem]:
    """Drop weak lexical matches when stronger evidence exists.

    Social-source items with zero engagement get a stricter threshold
    because zero engagement on a social platform is a strong noise signal.

    TikTok items with fewer than 1000 views are pruned
    (unless they are the only source represented in the batch).
    """
    sources_present = {item.source for item in items}

    def passes(item: schema.SourceItem) -> bool:
        # YouTube items with successfully extracted transcripts should not
        # be pruned by title-only relevance scoring -- the transcript content
        # already proves substantive topical coverage.
        if item.source == "youtube" and item.snippet:
            return True
        rel = item.local_relevance if item.local_relevance is not None else 0.0
        if rel < minimum:
            return False
        if item.source in _SOCIAL_SOURCES and (item.engagement_score is None or item.engagement_score == 0):
            if rel < minimum * 1.5:
                return False
        sole_source = sources_present == {item.source}
        if not _passes_engagement_floor(item, sole_source):
            return False
        return True

    filtered = [item for item in items if passes(item)]
    return filtered or items
