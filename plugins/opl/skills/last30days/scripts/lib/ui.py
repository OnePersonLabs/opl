"""Minimal stderr progress reporting for the curated CLI."""

from __future__ import annotations

import sys


SOURCE_LABELS = {
    "reddit": "Reddit",
    "x": "X",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "hackernews": "Hacker News",
    "polymarket": "Polymarket",
    "github": "GitHub",
    "grounding": "Web",
}


class ProgressDisplay:
    """Emit stable progress lines without banners, animation, or promotions."""

    def __init__(self, topic: str, show_banner: bool = True) -> None:
        self.topic = topic
        self.show_banner = show_banner
        self._ended = False

    def start_processing(self) -> None:
        sys.stderr.write(f"[last30days] Researching: {self.topic}\n")
        sys.stderr.flush()

    def end_processing(self) -> None:
        self._ended = True

    def show_complete(
        self,
        *,
        source_counts: dict[str, int],
        display_sources: list[str] | None = None,
    ) -> None:
        self.end_processing()
        ordered = list(dict.fromkeys(display_sources or source_counts.keys()))
        parts = [
            f"{SOURCE_LABELS.get(source, source)}={source_counts.get(source, 0)}"
            for source in ordered
        ]
        summary = ", ".join(parts) if parts else "no source results"
        sys.stderr.write(f"[last30days] Retrieval complete: {summary}\n")
        sys.stderr.flush()

    def show_error(self, message: str) -> None:
        self.end_processing()
        sys.stderr.write(f"[last30days] Error: {message}\n")
        sys.stderr.flush()
