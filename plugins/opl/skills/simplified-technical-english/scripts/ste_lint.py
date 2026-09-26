#!/usr/bin/env python3
"""Report mechanical clarity issues in eligible Markdown prose.

This advisory checker does not edit text or certify ASD-STE100 compliance.
The caller selects eligible content and its mode; filenames do not classify it.
"""

import argparse
from pathlib import Path
import re
import sys


WORD = re.compile(r"\b[\w]+(?:[-'][\w]+)*\b", re.UNICODE)
CONTRACTION = re.compile(r"\b[\w]+(?:n't|'(?:re|ve|ll|d|m|s))\b", re.IGNORECASE)
EMPTY_WORDS = re.compile(
    r"\b(?:seamless(?:ly)?|robust|leverage(?:d|s|ing)?|"
    r"utiliz(?:e|ed|es|ing)|cutting-edge|world-class|"
    r"it is (?:important to note|worth noting))\b",
    re.IGNORECASE,
)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`])")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
LIST_PREFIX = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def prose_blocks(markdown):
    """Yield (starting line, text) for prose, excluding syntax and quotations."""
    lines = []
    start = 0
    fence_char = None
    fence_length = 0

    def flush():
        nonlocal lines
        if lines:
            block = (start, " ".join(lines))
            lines = []
            return block
        return None

    for number, raw in enumerate(markdown.splitlines(), 1):
        fence = FENCE.match(raw)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                block = flush()
                if block:
                    yield block
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
            continue
        if fence_char is not None:
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", ">", "|", "<!--")):
            block = flush()
            if block:
                yield block
            continue
        listed = LIST_PREFIX.match(raw)
        if listed:
            block = flush()
            if block:
                yield block
            raw = raw[listed.end():]
        if not lines:
            start = number
        cleaned = LINK.sub(r"\1", raw)
        cleaned = INLINE_CODE.sub(" CODE ", cleaned)
        lines.append(cleaned.strip())
        if listed:
            block = flush()
            if block:
                yield block
    block = flush()
    if block:
        yield block


def lint(markdown, mode):
    limit = 25 if mode == "normative" else 32
    findings = []
    for line, block in prose_blocks(markdown):
        for sentence in SENTENCE_END.split(block):
            count = len(WORD.findall(sentence))
            if count > limit:
                findings.append((line, "long-sentence", f"{count} words; review the {limit}-word guide"))
            if CONTRACTION.search(sentence):
                findings.append((line, "contraction", "review contraction for ambiguity"))
            for match in EMPTY_WORDS.finditer(sentence):
                findings.append((line, "empty-word", f"review '{match.group()}' for a concrete meaning"))
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("normative", "guidance"), required=True)
    parser.add_argument("paths", metavar="PATH", nargs="+", help="eligible Markdown files, or - for stdin")
    args = parser.parse_args(argv)
    for name in args.paths:
        try:
            body = sys.stdin.read() if name == "-" else Path(name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            parser.error(f"cannot read {name}: {error}")
        for line, code, message in lint(body, args.mode):
            print(f"{name}:{line}: {code}: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
