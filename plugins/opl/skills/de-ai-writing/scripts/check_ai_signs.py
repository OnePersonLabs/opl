#!/usr/bin/env python3
"""Advisory scanner for mechanically detectable signs of AI-shaped prose."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from typing import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen


SOURCE_REVISION = 1376434705
SOURCE_TIMESTAMP = "2026-09-24T03:34:26Z"
SOURCE_REVIEWED = date.fromisoformat("2026-09-25")
SOURCE_INTERVAL_DAYS = 30
SOURCE_API = (
    "https://en.wikipedia.org/w/api.php?action=query&prop=revisions&"
    "rvprop=ids%7Ctimestamp&titles=Wikipedia%3ASigns_of_AI_writing&"
    "format=json&formatversion=2"
)
SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".html", ".htm"}


@dataclass(frozen=True)
class Rule:
    identifier: str
    name: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule_id: str
    rule_name: str
    excerpt: str


def compiled(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


RULES = (
    Rule("1.1", "undue significance", compiled(
        r"\b(?:stands|serves) as (?:a |an )?(?:testament|reminder|symbol)",
        r"\b(?:crucial|pivotal|vital|significant|key) (?:role|moment|turning point)\b",
        r"\b(?:reflects? broader|enduring legacy|indelible mark|setting the stage for)\b",
        r"\b(?:underscores?|highlights?) (?:its|the) importance\b",
    )),
    Rule("1.2", "canned notability", compiled(
        r"\b(?:independent coverage|leading expert|active social media presence)\b",
        r"\b(?:featured|profiled|covered) in (?:local|national|international|major)\b",
    )),
    Rule("1.3", "superficial analysis", compiled(
        r",\s+(?:highlighting|underscoring|emphasi[sz]ing|ensuring|reflecting|symboli[sz]ing|showcasing|fostering|cultivating|enhancing|contributing to)\b",
    )),
    Rule("1.4", "promotional language", compiled(
        r"\b(?:nestled|in the heart of|diverse array|breathtaking|world-class|state-of-the-art|groundbreaking|seamless)\b",
        r"\b(?:vibrant|rich) (?:culture|heritage|history|community)\b",
        r"\bcommitment to (?:quality|excellence|innovation)\b",
    )),
    Rule("1.5", "vague attribution", compiled(
        r"\b(?:experts?|observers?|critics?) (?:argue|say|note|believe|have cited)\b",
        r"\b(?:studies show|industry reports|widely regarded|several sources)\b",
    )),
    Rule("1.6", "challenges formula", compiled(
        r"\bdespite (?:these|the) challenges\b",
        r"\bfaces? (?:several|numerous|a number of) challenges\b",
    )),
    Rule("1.7", "title-defining lead", compiled(
        r"^[A-Z][^.!?]{0,100}\brefers to\b",
        r"\b(?:curated|comprehensive) compilation of\b",
    )),
    Rule("2.2", "copula avoidance", compiled(
        r"\b(?:serves|stands|functions|operates) as\b",
        r"\b(?:boasts|features|maintains|offers) (?:a|an|the|[0-9])\b",
    )),
    Rule("2.3", "vague association", compiled(
        r"\b(?:associated with|in connection with|connected to)\b",
    )),
    Rule("2.4", "negative parallelism", compiled(
        r"\bnot only\b.{0,100}\bbut also\b",
        r"\bnot just\b.{0,100}\b(?:but|it(?:'|’)s)\b",
        r"\bthis (?:is not|isn't|isn’t)\b.{0,100}\b(?:but|it(?:'|’)s)\b",
        r"\b(?:it(?:'|’)s|this is)\s+[^.!?]{1,100},\s*not\b",
        r"\b(?:it(?:'|’)s|this is)\s+not\b.{0,100},\s*(?:it(?:'|’)s|this is)\b",
        r"\bno [^,.!?]{1,40},\s*no [^,.!?]{1,40},\s*just\b",
    )),
    Rule("2.5", "generic significance framing", compiled(
        r"\bwhy (?:it|this|that) matters\b",
        r"\bwhat matters (?:is|here is)\b",
        r"\b(?:the|a) (?:detail|thing|part|point) that matters\b",
        r"\bthat matters\b",
    )),
    Rule("2.8", "honest as a generic style cue", compiled(
        r"\bhonest(?:ly|y)?\b",
    )),
    Rule("3.4", "em-dash overuse", compiled(
        r"\s—\s",
        r"—[^—\n]{0,120}—",
    )),
    Rule("4.1", "chat residue", compiled(
        r"\b(?:certainly|great question|I hope this helps)\b",
        r"\b(?:let me know if|would you like me to|in this section, we will discuss)\b",
    )),
    Rule("4.2", "cutoff disclaimer", compiled(
        r"\b(?:as of my last update|based on available information|not widely documented|specific details are limited)\b",
        r"\bmaintains? a low profile\b",
    )),
    Rule("4.3", "placeholder", compiled(
        r"\[(?:your name|describe [^\]]+|insert [^\]]+)\]",
        r"\b(?:INSERT_URL|20\d\d-XX-XX|TBD|TODO)\b",
    )),
    Rule("5.1", "didactic disclaimer", compiled(
        r"\b(?:it is|it's|it’s) (?:important|worthwhile) to (?:note|remember|consider)\b",
        r"\bit is worth noting\b|\bkeep in mind\b|\bmay vary\b",
    )),
    Rule("5.2", "summary ending", compiled(
        r"^(?:in summary|in conclusion|overall|ultimately)\b",
    )),
)

AI_VOCABULARY = compiled(
    r"\badditionally\b", r"\bbolstered\b", r"\bcrucial\b", r"\bdelve\b",
    r"\bemphasi[sz](?:e|ing)\b", r"\benhanc(?:e|ing)\b", r"\benduring\b",
    r"\bfoster(?:s|ed|ing)?\b", r"\bgarner(?:s|ed|ing)?\b", r"\bintricate\b",
    r"\binterplay\b", r"\blandscape\b", r"\bmeticulous\b", r"\bpivotal\b",
    r"\brobust\b", r"\bshowcas(?:e|es|ed|ing)\b", r"\btapestry\b",
    r"\btestament\b", r"\bunderscor(?:e|es|ed|ing)\b", r"\bvaluable insights?\b",
    r"\bvibrant\b",
)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
INLINE_CODE = re.compile(r"`[^`]*`")
QUOTED_TEXT = re.compile(r'(?s)(?:"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|\'[^\'\n]*\')')
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
TITLE_WORD = re.compile(r"^[A-Z][A-Za-z0-9'’:-]*$")


class TextHTMLParser(HTMLParser):
    """Collect visible, non-quoted HTML text with approximate source lines."""

    SKIP = {"script", "style", "pre", "code", "blockquote", "q"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in self.SKIP:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self.SKIP and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data.strip():
            self.parts.append((self.getpos()[0], data))


def remove_protected_text(text: str) -> str:
    text = INLINE_CODE.sub(" ", text)
    text = MARKDOWN_LINK.sub(r"\1", text)
    return QUOTED_TEXT.sub(" ", text)


def markdown_segments(text: str) -> tuple[list[tuple[int, str, str]], list[Finding]]:
    segments: list[tuple[int, str, str]] = []
    findings: list[Finding] = []
    in_fence = False
    fence_marker = ""
    in_frontmatter = text.startswith("---\n") or text.startswith("---\r\n")
    breaks: list[int] = []

    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if number == 1 and in_frontmatter:
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        fence = re.match(r"^\s*(```+|~~~+)", raw)
        if fence:
            marker = fence.group(1)[0]
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            continue
        if in_fence or re.match(r"^\s*>", raw):
            continue
        if re.match(r"^\s{0,3}(?:---+|___+|\*\*\*+)\s*$", raw):
            breaks.append(number)
            continue

        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", raw)
        if heading and is_title_case_heading(heading.group(1)):
            findings.append(Finding("", number, "3.1", "title-style heading", heading.group(1)))
        if len(re.findall(r"\*\*[^*\n]+\*\*", raw)) >= 3:
            findings.append(Finding("", number, "3.2", "excess boldface", stripped))
        if re.match(r"^\s*[-*+]\s+\*\*[^*\n]+:\*\*", raw):
            findings.append(Finding("", number, "3.3", "inline-header list", stripped))
        if re.match(r"^\s*(?:#{1,6}|[-*+])\s+[\U0001F1E6-\U0001FAFF\u2600-\u27BF]", raw):
            findings.append(Finding("", number, "3.5", "emoji as structure", stripped))

        cleaned = remove_protected_text(raw)
        for sentence in SENTENCE_SPLIT.split(cleaned):
            if sentence.strip():
                segments.append((number, sentence.strip(), stripped))

    if len(breaks) > 1:
        for number in breaks:
            findings.append(Finding("", number, "3.8", "repeated thematic breaks", "---"))
    return segments, findings


def html_segments(text: str) -> list[tuple[int, str, str]]:
    parser = TextHTMLParser()
    parser.feed(text)
    output: list[tuple[int, str, str]] = []
    for number, value in parser.parts:
        cleaned = remove_protected_text(value)
        for sentence in SENTENCE_SPLIT.split(cleaned):
            if sentence.strip():
                output.append((number, sentence.strip(), sentence.strip()))
    return output


def plain_segments(text: str) -> list[tuple[int, str, str]]:
    output: list[tuple[int, str, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        cleaned = remove_protected_text(raw)
        for sentence in SENTENCE_SPLIT.split(cleaned):
            if sentence.strip():
                output.append((number, sentence.strip(), raw.strip()))
    return output


def is_title_case_heading(value: str) -> bool:
    words = [re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9'’:-]+$", "", word) for word in value.split()]
    words = [word for word in words if word]
    if len(words) < 3:
        return False
    minor = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"}
    meaningful = [word for index, word in enumerate(words) if index == 0 or word.casefold() not in minor]
    return len(meaningful) >= 3 and all(TITLE_WORD.match(word) for word in meaningful)


def scan_text(text: str, path: str, suffix: str) -> list[Finding]:
    structural: list[Finding] = []
    if suffix in {".md", ".markdown"}:
        segments, structural = markdown_segments(text)
    elif suffix in {".html", ".htm"}:
        segments = html_segments(text)
    else:
        segments = plain_segments(text)

    findings = [Finding(path, item.line, item.rule_id, item.rule_name, item.excerpt) for item in structural]
    seen: set[tuple[int, str, str]] = set()
    for line, sentence, original in segments:
        for rule in RULES:
            if any(pattern.search(sentence) for pattern in rule.patterns):
                key = (line, rule.identifier, original)
                if key not in seen:
                    findings.append(Finding(path, line, rule.identifier, rule.name, original))
                    seen.add(key)
        vocabulary_hits = {pattern.pattern for pattern in AI_VOCABULARY if pattern.search(sentence)}
        if len(vocabulary_hits) >= 3:
            key = (line, "2.1", original)
            if key not in seen:
                findings.append(Finding(path, line, "2.1", "dense AI-associated vocabulary", original))
                seen.add(key)
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule_id))


def collect_paths(arguments: Iterable[str]) -> tuple[list[Path], bool]:
    files: list[Path] = []
    stdin_requested = False
    for value in arguments:
        if value == "-":
            stdin_requested = True
            continue
        path = Path(value)
        if not path.exists():
            raise ValueError(f"path does not exist: {path}")
        if path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file() and item.suffix.casefold() in SUPPORTED_SUFFIXES)
        elif path.suffix.casefold() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"unsupported file type: {path}")
        else:
            files.append(path)
    unique = sorted({item.resolve() for item in files}, key=lambda item: str(item).casefold())
    return unique, stdin_requested


def latest_source() -> tuple[int, str]:
    request = Request(SOURCE_API, headers={"User-Agent": "OPL-de-ai-writing/1.0 (source status check)"})
    last_error: OSError | URLError | None = None
    for attempt in range(1, 4):
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
            break
        except (OSError, URLError) as error:
            last_error = error
            if attempt == 3:
                raise
            delay = 0.25 * attempt
            print(f"WARN source-check retry={attempt} delay={delay:.2f}s error={type(error).__name__}", file=sys.stderr)
            time.sleep(delay)
    else:  # pragma: no cover - the final attempt always returns or raises
        assert last_error is not None
        raise last_error
    revision = payload["query"]["pages"][0]["revisions"][0]
    return int(revision["revid"]), str(revision["timestamp"])


def source_status(*, force: bool = False, today: date | None = None) -> int:
    current_date = today or date.today()
    next_check = SOURCE_REVIEWED + timedelta(days=SOURCE_INTERVAL_DAYS)
    if not force and current_date < next_check:
        print(f"local revision: {SOURCE_REVISION} ({SOURCE_TIMESTAMP})")
        print(f"status: not due until {next_check.isoformat()}")
        return 0
    try:
        revision, timestamp = latest_source()
    except (OSError, URLError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"source check failed: {error}", file=sys.stderr)
        return 2
    print(f"local revision: {SOURCE_REVISION} ({SOURCE_TIMESTAMP})")
    print(f"latest revision: {revision} ({timestamp})")
    if revision == SOURCE_REVISION:
        print("status: current")
        return 0
    print("status: stale")
    return 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("paths", nargs="*", help="files, directories, or - for stdin")
    result.add_argument("--summary", action="store_true", help="print counts by rule and file")
    result.add_argument("--source-status", action="store_true", help="compare the recorded Wikipedia revision with the live page")
    result.add_argument("--force-source-check", action="store_true", help="check the live source before the 30-day interval expires")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.source_status:
        if args.paths or args.summary:
            print("--source-status cannot be combined with paths or --summary", file=sys.stderr)
            return 2
        return source_status(force=args.force_source_check)
    if args.force_source_check:
        print("--force-source-check requires --source-status", file=sys.stderr)
        return 2
    if not args.paths:
        print("at least one path or - is required", file=sys.stderr)
        return 2

    try:
        paths, stdin_requested = collect_paths(args.paths)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    findings: list[Finding] = []
    if stdin_requested:
        findings.extend(scan_text(sys.stdin.read(), "<stdin>", ".txt"))
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            print(f"cannot read {path}: {error}", file=sys.stderr)
            return 2
        findings.extend(scan_text(content, str(path), path.suffix.casefold()))

    for finding in findings:
        excerpt = re.sub(r"\s+", " ", finding.excerpt).strip()
        print(f"{finding.path}:{finding.line}: [{finding.rule_id} {finding.rule_name}] {excerpt}")

    if args.summary:
        by_rule = Counter((item.rule_id, item.rule_name) for item in findings)
        by_file = Counter(item.path for item in findings)
        print(f"TOTAL {len(findings)}")
        for (identifier, name), count in sorted(by_rule.items()):
            print(f"RULE {identifier} {name}: {count}")
        for path, count in sorted(by_file.items()):
            print(f"FILE {path}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
