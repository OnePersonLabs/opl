#!/usr/bin/env python3
"""Token-bounded reader and search index for Codex rollout JSONL sessions."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "1"
PREFIX_BYTES = 4096
DEFAULT_LIMIT = 20
MAX_LIMIT = 200
DEFAULT_EXCERPT_CHARS = 240
DEFAULT_MESSAGE_CHARS = 4000
DEFAULT_OUTPUT_CHARS = 24000
HARD_OUTPUT_CHARS = 100000
SESSION_ID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


class ReaderError(RuntimeError):
    """An actionable command error."""


@dataclass(frozen=True)
class SourceFile:
    session_id: str
    path: Path
    archived: bool
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class ParsedMessage:
    raw_line: int
    byte_offset: int
    timestamp: str
    role: str
    phase: str
    source: str
    text: str


@dataclass
class ParseResult:
    session_id: str
    created_at: str
    updated_at: str
    cwd: str
    schema: str
    messages: list[ParsedMessage]
    fallback_messages: list[ParsedMessage]
    line_count: int
    malformed_count: int
    unknown_count: int
    complete_offset: int


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def codex_home_from(args: argparse.Namespace) -> Path:
    if args.codex_home:
        return Path(args.codex_home).expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".codex"


def cache_path_from(args: argparse.Namespace) -> Path:
    if args.cache:
        return Path(args.cache).expanduser().resolve()
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "session-reader" / "index.sqlite3"


def secure_cache_parent(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(PermissionError):
        path.parent.chmod(0o700)


def connect_db(path: Path) -> sqlite3.Connection:
    secure_cache_parent(path)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    initialize_schema(conn)
    conn.commit()
    with contextlib.suppress(PermissionError):
        path.chmod(0o600)
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            archived INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            cwd TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            prefix_len INTEGER NOT NULL,
            prefix_hash TEXT NOT NULL,
            indexed_offset INTEGER NOT NULL,
            line_count INTEGER NOT NULL,
            message_count INTEGER NOT NULL,
            malformed_count INTEGER NOT NULL,
            unknown_count INTEGER NOT NULL,
            schema_kind TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            message_no INTEGER NOT NULL,
            raw_line INTEGER NOT NULL,
            byte_offset INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            role TEXT NOT NULL,
            phase TEXT NOT NULL,
            source TEXT NOT NULL,
            text TEXT NOT NULL,
            UNIQUE(session_id, message_no)
        );
        CREATE INDEX IF NOT EXISTS messages_session_order
            ON messages(session_id, message_no);
        CREATE INDEX IF NOT EXISTS messages_timestamp
            ON messages(timestamp DESC);
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            text,
            content='messages',
            content_rowid='id',
            tokenize='unicode61'
        );
        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, text)
            VALUES ('delete', old.id, old.text);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, text)
            VALUES ('delete', old.id, old.text);
            INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
        END;
        """
    )
    row = conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if row and row[0] != SCHEMA_VERSION:
        raise ReaderError(
            f"Cache schema {row[0]} is incompatible with {SCHEMA_VERSION}; run index --rebuild"
        )
    conn.execute(
        "INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )


def session_id_from_path(path: Path) -> str | None:
    matches = SESSION_ID_RE.findall(path.name)
    return matches[-1].lower() if matches else None


def session_id_from_rollout(path: Path) -> str | None:
    """Read only the metadata prefix; payload identity is authoritative."""
    fallback = session_id_from_path(path)
    try:
        with path.open("rb") as handle:
            scanned = 0
            for _ in range(128):
                raw = handle.readline()
                if not raw:
                    break
                scanned += len(raw)
                if scanned > 1024 * 1024:
                    break
                try:
                    obj = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "session_meta":
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict):
                    continue
                meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else payload
                candidate = meta.get("id") or meta.get("session_id")
                if isinstance(candidate, str) and SESSION_ID_RE.fullmatch(candidate):
                    return candidate.lower()
    except FileNotFoundError:
        return None
    return fallback


def discover_sources(codex_home: Path) -> dict[str, SourceFile]:
    candidates: dict[str, list[SourceFile]] = {}
    roots = ((codex_home / "sessions", False), (codex_home / "archived_sessions", True))
    for root, archived in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            session_id = session_id_from_rollout(path)
            if not session_id:
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            candidates.setdefault(session_id, []).append(
                SourceFile(session_id, path.resolve(), archived, stat.st_size, stat.st_mtime_ns)
            )

    chosen: dict[str, SourceFile] = {}
    for session_id, files in candidates.items():
        # Prefer an active copy; otherwise prefer the newest surviving archive.
        chosen[session_id] = max(files, key=lambda item: (not item.archived, item.mtime_ns))
    return chosen


def prefix_fingerprint(path: Path, length: int | None = None) -> tuple[int, str]:
    size = path.stat().st_size
    prefix_len = min(size, PREFIX_BYTES) if length is None else min(size, length)
    with path.open("rb") as handle:
        data = handle.read(prefix_len)
    return prefix_len, hashlib.sha256(data).hexdigest()


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            value = block.get("text") or block.get("input_text") or block.get("output_text")
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def parse_message(obj: dict[str, Any], raw_line: int, offset: int) -> tuple[str, ParsedMessage] | None:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None
    timestamp = obj.get("timestamp") if isinstance(obj.get("timestamp"), str) else ""

    if obj.get("type") == "event_msg":
        event_type = payload.get("type")
        message = payload.get("message")
        if event_type == "user_message" and isinstance(message, str) and message.strip():
            return "canonical", ParsedMessage(
                raw_line, offset, timestamp, "user", "user", "event_msg", message
            )
        if event_type == "agent_message" and isinstance(message, str) and message.strip():
            phase = payload.get("phase")
            if not isinstance(phase, str) or not phase:
                phase = "final_answer"
            return "canonical", ParsedMessage(
                raw_line, offset, timestamp, "assistant", phase, "event_msg", message
            )

    if obj.get("type") == "response_item" and payload.get("type") == "message":
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return None
        text = text_from_content(payload.get("content"))
        if not text.strip():
            return None
        phase = "user" if role == "user" else payload.get("phase") or "final_answer"
        return "fallback", ParsedMessage(
            raw_line, offset, timestamp, role, str(phase), "response_item_fallback", text
        )
    return None


def parse_rollout(
    source: SourceFile,
    *,
    start_offset: int = 0,
    start_line: int = 0,
    canonical_only: bool = False,
) -> ParseResult:
    canonical: list[ParsedMessage] = []
    fallback: list[ParsedMessage] = []
    malformed = 0
    unknown = 0
    line_no = start_line
    complete_offset = start_offset
    session_id = source.session_id
    created_at = ""
    updated_at = ""
    cwd = ""
    meta_seen = False

    with source.path.open("rb") as handle:
        handle.seek(start_offset)
        while True:
            offset = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            has_newline = raw.endswith(b"\n")
            try:
                obj = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                if not has_newline:
                    # A live writer may not have completed the final JSON record.
                    handle.seek(offset)
                    break
                malformed += 1
                line_no += 1
                complete_offset = handle.tell()
                continue

            line_no += 1
            complete_offset = handle.tell()
            if not isinstance(obj, dict):
                unknown += 1
                continue
            if obj.get("type") not in {
                "session_meta",
                "turn_context",
                "event_msg",
                "response_item",
                "world_state",
            }:
                unknown += 1
            timestamp = obj.get("timestamp")
            if isinstance(timestamp, str):
                created_at = created_at or timestamp
                updated_at = timestamp
            if (
                obj.get("type") == "session_meta"
                and isinstance(obj.get("payload"), dict)
                and not meta_seen
            ):
                meta_seen = True
                payload = obj["payload"]
                meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else payload
                candidate_id = meta.get("id") or meta.get("session_id")
                if isinstance(candidate_id, str):
                    session_id = candidate_id.lower()
                if isinstance(meta.get("timestamp"), str):
                    created_at = meta["timestamp"]
                if isinstance(meta.get("cwd"), str):
                    cwd = meta["cwd"]
            elif obj.get("type") == "turn_context" and isinstance(obj.get("payload"), dict):
                turn_cwd = obj["payload"].get("cwd")
                if isinstance(turn_cwd, str):
                    cwd = turn_cwd

            parsed = parse_message(obj, line_no, offset)
            if parsed:
                kind, message = parsed
                if kind == "canonical":
                    canonical.append(message)
                elif not canonical_only:
                    fallback.append(message)

    chosen_schema = "event_msg" if canonical else "response_item_fallback"
    if canonical_only:
        chosen_schema = "event_msg"
    return ParseResult(
        session_id=session_id,
        created_at=created_at,
        updated_at=updated_at or created_at,
        cwd=cwd,
        schema=chosen_schema,
        messages=canonical,
        fallback_messages=fallback,
        line_count=line_no,
        malformed_count=malformed,
        unknown_count=unknown,
        complete_offset=complete_offset,
    )


def insert_messages(
    conn: sqlite3.Connection,
    session_id: str,
    messages: Sequence[ParsedMessage],
    start_number: int = 1,
) -> None:
    conn.executemany(
        """
        INSERT INTO messages(
            session_id, message_no, raw_line, byte_offset, timestamp,
            role, phase, source, text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                session_id,
                start_number + index,
                msg.raw_line,
                msg.byte_offset,
                msg.timestamp,
                msg.role,
                msg.phase,
                msg.source,
                msg.text,
            )
            for index, msg in enumerate(messages)
        ],
    )


def full_index(conn: sqlite3.Connection, source: SourceFile) -> tuple[str, int]:
    parsed = parse_rollout(source)
    if parsed.session_id != source.session_id:
        raise ReaderError(
            f"Session id mismatch in {source.path}: filename={source.session_id} payload={parsed.session_id}"
        )
    messages = parsed.messages if parsed.messages else parsed.fallback_messages
    prefix_len, prefix_hash = prefix_fingerprint(source.path)
    conn.execute(
        "DELETE FROM sessions WHERE path=? AND session_id<>?",
        (str(source.path), source.session_id),
    )
    conn.execute("DELETE FROM sessions WHERE session_id=?", (source.session_id,))
    conn.execute(
        """
        INSERT INTO sessions(
            session_id, path, archived, created_at, updated_at, cwd, size, mtime_ns,
            prefix_len, prefix_hash, indexed_offset, line_count, message_count,
            malformed_count, unknown_count, schema_kind
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source.session_id,
            str(source.path),
            int(source.archived),
            parsed.created_at,
            parsed.updated_at,
            parsed.cwd,
            source.size,
            source.mtime_ns,
            prefix_len,
            prefix_hash,
            parsed.complete_offset,
            parsed.line_count,
            len(messages),
            parsed.malformed_count,
            parsed.unknown_count,
            parsed.schema,
        ),
    )
    insert_messages(conn, source.session_id, messages)
    return "reindexed", len(messages)


def refresh_index(
    conn: sqlite3.Connection,
    codex_home: Path,
    *,
    prune: bool = True,
) -> dict[str, int]:
    sources = discover_sources(codex_home)
    existing = {
        row["session_id"]: row
        for row in conn.execute("SELECT * FROM sessions").fetchall()
    }
    stats = {"discovered": len(sources), "unchanged": 0, "appended": 0, "reindexed": 0, "pruned": 0}

    if prune:
        for session_id in set(existing) - set(sources):
            conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            stats["pruned"] += 1

    for session_id, source in sources.items():
        old = existing.get(session_id)
        if old is None:
            full_index(conn, source)
            stats["reindexed"] += 1
            conn.commit()
            continue

        unchanged_content = old["size"] == source.size and old["mtime_ns"] == source.mtime_ns
        if unchanged_content:
            if old["path"] != str(source.path) or bool(old["archived"]) != source.archived:
                conn.execute(
                    "UPDATE sessions SET path=?, archived=? WHERE session_id=?",
                    (str(source.path), int(source.archived), session_id),
                )
                conn.commit()
            stats["unchanged"] += 1
            continue

        _, current_hash = prefix_fingerprint(source.path, old["prefix_len"])
        prefix_matches = current_hash == old["prefix_hash"]
        can_append = (
            source.size >= old["indexed_offset"]
            and prefix_matches
            and old["schema_kind"] == "event_msg"
        )
        if can_append and source.size > old["indexed_offset"]:
            parsed = parse_rollout(
                source,
                start_offset=old["indexed_offset"],
                start_line=old["line_count"],
                canonical_only=True,
            )
            insert_messages(conn, session_id, parsed.messages, old["message_count"] + 1)
            conn.execute(
                """
                UPDATE sessions SET path=?, archived=?, updated_at=COALESCE(NULLIF(?, ''), updated_at),
                    cwd=COALESCE(NULLIF(?, ''), cwd), size=?, mtime_ns=?, indexed_offset=?,
                    line_count=?, message_count=?, malformed_count=malformed_count+?,
                    unknown_count=unknown_count+?
                WHERE session_id=?
                """,
                (
                    str(source.path),
                    int(source.archived),
                    parsed.updated_at,
                    parsed.cwd,
                    source.size,
                    source.mtime_ns,
                    parsed.complete_offset,
                    parsed.line_count,
                    old["message_count"] + len(parsed.messages),
                    parsed.malformed_count,
                    parsed.unknown_count,
                    session_id,
                ),
            )
            stats["appended"] += 1
            conn.commit()
            continue

        # A pure metadata/path change can preserve indexed messages.
        if source.size == old["size"] and prefix_matches:
            conn.execute(
                "UPDATE sessions SET path=?, archived=?, mtime_ns=? WHERE session_id=?",
                (str(source.path), int(source.archived), source.mtime_ns, session_id),
            )
            stats["unchanged"] += 1
            conn.commit()
            continue

        full_index(conn, source)
        stats["reindexed"] += 1
        conn.commit()

    conn.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES ('last_refresh', ?)",
        (dt.datetime.now(dt.timezone.utc).isoformat(),),
    )
    conn.commit()
    return stats


def split_csv(value: str | None) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()] if value else []


def normalize_roles(value: str | None) -> list[str]:
    roles = ["assistant" if item == "agent" else item for item in split_csv(value)]
    invalid = set(roles) - {"user", "assistant"}
    if invalid:
        raise ReaderError(f"Unsupported roles: {', '.join(sorted(invalid))}")
    return roles


def normalize_phases(value: str | None) -> list[str]:
    phases = split_csv(value)
    invalid = set(phases) - {"user", "commentary", "final_answer"}
    if invalid:
        raise ReaderError(f"Unsupported phases: {', '.join(sorted(invalid))}")
    return phases


def parse_range(value: str | None) -> tuple[int, int | None]:
    if not value:
        return 1, None
    if ":" not in value:
        try:
            number = int(value)
        except ValueError as exc:
            raise ReaderError("Range must be N, START:END, START:, or :END") from exc
        if number < 1:
            raise ReaderError("Message numbers start at 1")
        return number, number
    left, right = value.split(":", 1)
    try:
        start = int(left) if left else 1
        end = int(right) if right else None
    except ValueError as exc:
        raise ReaderError("Range must contain positive integers") from exc
    if start < 1 or (end is not None and end < start):
        raise ReaderError("Range start must be positive and no greater than its end")
    return start, end


def session_matches(row: sqlite3.Row, args: argparse.Namespace) -> bool:
    if getattr(args, "archive", "both") == "active" and row["archived"]:
        return False
    if getattr(args, "archive", "both") == "archived" and not row["archived"]:
        return False
    cwd_pattern = getattr(args, "cwd", None)
    if cwd_pattern and not (
        fnmatch.fnmatch(row["cwd"], cwd_pattern) or cwd_pattern.lower() in row["cwd"].lower()
    ):
        return False
    since = getattr(args, "since", None)
    until = getattr(args, "until", None)
    if since and row["updated_at"] < since:
        return False
    if until and row["updated_at"] > until:
        return False
    return True


def resolve_session(conn: sqlite3.Connection, selector: str) -> sqlite3.Row:
    candidate = Path(selector).expanduser()
    if candidate.is_file():
        resolved = str(candidate.resolve())
        row = conn.execute("SELECT * FROM sessions WHERE path=?", (resolved,)).fetchone()
        if row:
            return row
        raise ReaderError(f"Session path is not indexed: {resolved}")
    exact = conn.execute("SELECT * FROM sessions WHERE session_id=?", (selector.lower(),)).fetchone()
    if exact:
        return exact
    rows = conn.execute(
        "SELECT * FROM sessions WHERE session_id LIKE ? ORDER BY updated_at DESC",
        (selector.lower() + "%",),
    ).fetchall()
    if not rows:
        raise ReaderError(f"No indexed session matches: {selector}")
    if len(rows) > 1:
        ids = ", ".join(row["session_id"] for row in rows[:5])
        raise ReaderError(f"Ambiguous session prefix {selector!r}; matches: {ids}")
    return rows[0]


def row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
        "archived": bool(row["archived"]),
        "path": row["path"],
        "cwd": row["cwd"],
        "size": row["size"],
        "message_count": row["message_count"],
        "schema": row["schema_kind"],
    }


def row_to_message(row: sqlite3.Row, *, text: str | None = None) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "path": row["path"],
        "message_no": row["message_no"],
        "raw_line": row["raw_line"],
        "byte_offset": row["byte_offset"],
        "timestamp": row["timestamp"],
        "role": row["role"],
        "phase": row["phase"],
        "source": row["source"],
        "text": row["text"] if text is None else text,
    }


def emit(payload: Any, fmt: str, *, kind: str = "result") -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif fmt == "jsonl":
        if isinstance(payload, list):
            for item in payload:
                print(json.dumps({"type": kind, **item}, ensure_ascii=False))
        else:
            print(json.dumps({"type": kind, **payload}, ensure_ascii=False))
    else:
        raise AssertionError("Text output must be rendered by the command")


def compact_excerpt(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 1)] + "…"


def clip_message(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = f"\n… [{len(text) - limit} characters omitted]"
    keep = max(0, limit - len(marker))
    return text[:keep] + marker, True


def command_sessions(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC").fetchall()
    if args.session:
        target = resolve_session(conn, args.session)["session_id"]
        rows = [row for row in rows if row["session_id"] == target]
    rows = [row for row in rows if session_matches(row, args)][: args.limit]
    payload = [row_to_session(row) for row in rows]
    if args.format != "text":
        emit(payload, args.format, kind="session")
        return
    print(f"sessions={len(payload)} limit={args.limit}")
    for item in payload:
        state = "archived" if item["archived"] else "active"
        print(
            f"{item['updated_at']} {item['session_id']} {state} messages={item['message_count']} "
            f"size={item['size']} cwd={item['cwd']}\n  {item['path']}"
        )


def command_inspect(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    row = resolve_session(conn, args.session)
    groups = conn.execute(
        "SELECT role, phase, COUNT(*) count FROM messages WHERE session_id=? GROUP BY role, phase",
        (row["session_id"],),
    ).fetchall()
    path = Path(row["path"])
    try:
        stat = path.stat()
        stale = stat.st_size != row["size"] or stat.st_mtime_ns != row["mtime_ns"]
    except FileNotFoundError:
        stale = True
    payload = {
        **row_to_session(row),
        "raw_line_count": row["line_count"],
        "indexed_offset": row["indexed_offset"],
        "malformed_count": row["malformed_count"],
        "unknown_count": row["unknown_count"],
        "stale": stale,
        "groups": [dict(item) for item in groups],
    }
    if args.format != "text":
        emit(payload, args.format, kind="inspection")
        return
    for key, value in payload.items():
        if key != "groups":
            print(f"{key}: {value}")
    print("groups:")
    for group in payload["groups"]:
        print(f"  {group['role']}/{group['phase']}: {group['count']}")


def fetch_show_rows(conn: sqlite3.Connection, args: argparse.Namespace, session_id: str) -> list[sqlite3.Row]:
    start, end = parse_range(args.range)
    clauses = ["m.session_id=?", "m.message_no>=?"]
    values: list[Any] = [session_id, start]
    if end is not None:
        clauses.append("m.message_no<=?")
        values.append(end)
    if args.view == "conversation":
        clauses.append("(m.role='user' OR (m.role='assistant' AND m.phase='final_answer'))")
    roles = normalize_roles(args.roles)
    phases = normalize_phases(args.phases)
    if roles:
        clauses.append(f"m.role IN ({','.join('?' for _ in roles)})")
        values.extend(roles)
    if phases:
        clauses.append(f"m.phase IN ({','.join('?' for _ in phases)})")
        values.extend(phases)
    return conn.execute(
        f"""
        SELECT m.*, s.path FROM messages m JOIN sessions s USING(session_id)
        WHERE {' AND '.join(clauses)} ORDER BY m.message_no
        """,
        values,
    ).fetchall()


def bounded_messages(rows: Sequence[sqlite3.Row], args: argparse.Namespace) -> tuple[list[dict[str, Any]], bool, int | None]:
    emitted: list[dict[str, Any]] = []
    used = 0
    truncated = False
    next_start: int | None = None
    for row in rows:
        clipped, body_truncated = clip_message(row["text"], args.message_chars)
        cost = len(clipped)
        if emitted and used + cost > args.max_output_chars:
            truncated = True
            next_start = row["message_no"]
            break
        if not emitted and cost > args.max_output_chars:
            clipped, body_truncated = clip_message(clipped, args.max_output_chars)
            cost = len(clipped)
        item = row_to_message(row, text=clipped)
        item["body_truncated"] = body_truncated
        emitted.append(item)
        used += cost
    return emitted, truncated, next_start


def command_show(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    session = resolve_session(conn, args.session)
    rows = fetch_show_rows(conn, args, session["session_id"])
    messages, truncated, next_start = bounded_messages(rows, args)
    payload = {
        "session": row_to_session(session),
        "view": args.view,
        "selected_count": len(rows),
        "emitted_count": len(messages),
        "truncated": truncated,
        "next_start": next_start,
        "messages": messages,
    }
    if args.format == "json":
        emit(payload, "json")
        return
    if args.format == "jsonl":
        print(json.dumps({"type": "meta", **{k: v for k, v in payload.items() if k != "messages"}}, ensure_ascii=False))
        for message in messages:
            print(json.dumps({"type": "message", **message}, ensure_ascii=False))
        return
    print(
        f"session={session['session_id']} view={args.view} selected={len(rows)} "
        f"emitted={len(messages)} total_messages={session['message_count']} path={session['path']}"
    )
    for message in messages:
        role = "agent" if message["role"] == "assistant" else "user"
        print(
            f"\n[M{message['message_no']:06d} L{message['raw_line']:06d} B{message['byte_offset']:012d} "
            f"{message['timestamp']}] {role}/{message['phase']} ({message['source']})\n{message['text']}"
        )
    if truncated:
        print(f"\n[TRUNCATED] Continue with --range {next_start}: --view {args.view}")


def search_rows(conn: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    params: list[Any] = []
    where: list[str] = []
    if args.mode == "fts":
        sql = """
            SELECT m.*, s.path, s.cwd, s.archived, s.updated_at session_updated,
                   bm25(messages_fts) AS rank
            FROM messages_fts
            JOIN messages m ON m.id=messages_fts.rowid
            JOIN sessions s ON s.session_id=m.session_id
        """
        message_alias = "m"
        where.append("messages_fts MATCH ?")
        params.append(args.query)
    else:
        sql = """
            SELECT m.*, s.path, s.cwd, s.archived, s.updated_at session_updated,
                   0.0 AS rank
            FROM messages m
            JOIN sessions s USING(session_id)
        """
        message_alias = "m"
        if args.mode == "literal":
            where.append(f"instr(lower({message_alias}.text), lower(?)) > 0")
            params.append(args.query)

    if args.session:
        session = resolve_session(conn, args.session)
        where.append(f"{message_alias}.session_id=?")
        params.append(session["session_id"])
    roles = normalize_roles(args.roles)
    phases = normalize_phases(args.phases)
    if roles:
        where.append(f"{message_alias}.role IN ({','.join('?' for _ in roles)})")
        params.extend(roles)
    if phases:
        where.append(f"{message_alias}.phase IN ({','.join('?' for _ in phases)})")
        params.extend(phases)
    if args.since:
        where.append(f"{message_alias}.timestamp>=?")
        params.append(args.since)
    if args.until:
        where.append(f"{message_alias}.timestamp<=?")
        params.append(args.until)
    if args.archive == "active":
        where.append("s.archived=0")
    elif args.archive == "archived":
        where.append("s.archived=1")
    if args.cwd:
        where.append("lower(s.cwd) LIKE lower(?)")
        params.append(f"%{args.cwd}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    try:
        candidates = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if args.mode == "fts":
            raise ReaderError(f"Invalid FTS query {args.query!r}: {exc}") from exc
        raise

    if args.mode == "regex":
        try:
            pattern = re.compile(args.query, re.IGNORECASE if args.ignore_case else 0)
        except re.error as exc:
            raise ReaderError(f"Invalid regular expression: {exc}") from exc
        candidates = [row for row in candidates if pattern.search(row["text"])]
    if args.order == "rank" and args.mode == "fts":
        candidates.sort(
            key=lambda row: (row["timestamp"], row["session_id"], row["message_no"]),
            reverse=True,
        )
        candidates.sort(key=lambda row: row["rank"])
    elif args.order == "oldest":
        candidates.sort(key=lambda row: (row["timestamp"], row["session_id"], row["message_no"]))
    else:
        candidates.sort(
            key=lambda row: (row["timestamp"], row["session_id"], row["message_no"]),
            reverse=True,
        )
    return candidates[args.offset :]


def context_for(conn: sqlite3.Connection, row: sqlite3.Row, radius: int) -> list[dict[str, Any]]:
    if radius <= 0:
        return []
    rows = conn.execute(
        """
        SELECT m.*, s.path FROM messages m JOIN sessions s USING(session_id)
        WHERE m.session_id=? AND m.message_no BETWEEN ? AND ? ORDER BY m.message_no
        """,
        (row["session_id"], max(1, row["message_no"] - radius), row["message_no"] + radius),
    ).fetchall()
    return [
        row_to_message(item, text=compact_excerpt(item["text"], DEFAULT_EXCERPT_CHARS))
        for item in rows
        if item["message_no"] != row["message_no"]
    ]


def command_search(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    candidates = search_rows(conn, args)
    rows = candidates[: args.limit]
    has_more = len(candidates) > args.limit
    results: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for row in rows:
        item = row_to_message(row, text=compact_excerpt(row["text"], args.excerpt_chars))
        cost = len(item["text"])
        if results and used + cost > args.max_output_chars:
            truncated = True
            break
        if args.context:
            context = context_for(conn, row, args.context)
            bounded_context: list[dict[str, Any]] = []
            for surrounding in context:
                context_cost = len(surrounding["text"])
                if used + cost + context_cost > args.max_output_chars:
                    item["context_truncated"] = True
                    break
                bounded_context.append(surrounding)
                cost += context_cost
            item["context"] = bounded_context
        results.append(item)
        used += cost
    next_offset = args.offset + len(results) if truncated or has_more else None
    payload = {
        "query": args.query,
        "mode": args.mode,
        "count": len(results),
        "offset": args.offset,
        "truncated": truncated,
        "has_more": has_more,
        "next_offset": next_offset,
        "results": results,
    }
    if args.format == "json":
        emit(payload, "json")
        return
    if args.format == "jsonl":
        print(
            json.dumps(
                {
                    "type": "meta",
                    "query": args.query,
                    "mode": args.mode,
                    "count": len(results),
                    "offset": args.offset,
                    "truncated": truncated,
                    "has_more": has_more,
                    "next_offset": next_offset,
                },
                ensure_ascii=False,
            )
        )
        for item in results:
            print(json.dumps({"type": "match", **item}, ensure_ascii=False))
        return
    print(
        f"query={args.query!r} mode={args.mode} matches={len(results)} "
        f"order={args.order} has_more={str(has_more).lower()}"
    )
    for item in results:
        role = "agent" if item["role"] == "assistant" else "user"
        print(
            f"{item['timestamp']} {item['session_id']} M{item['message_no']:06d} "
            f"L{item['raw_line']:06d} B{item['byte_offset']:012d} {role}/{item['phase']}\n"
            f"  {item['text']}\n  {item['path']}"
        )
        for surrounding in item.get("context", []):
            print(
                f"    context M{surrounding['message_no']:06d} "
                f"{surrounding['role']}/{surrounding['phase']}: {surrounding['text']}"
            )
    if truncated or has_more:
        reason = "output cap" if truncated else "result limit"
        print(f"[MORE: {reason}] Continue with --offset {next_offset}")


def stale_count(conn: sqlite3.Connection, codex_home: Path) -> tuple[int, int]:
    discovered = discover_sources(codex_home)
    indexed = {
        row["session_id"]: row
        for row in conn.execute("SELECT session_id, path, size, mtime_ns FROM sessions")
    }
    stale = len(set(indexed) ^ set(discovered))
    for session_id in set(indexed) & set(discovered):
        row = indexed[session_id]
        source = discovered[session_id]
        if row["path"] != str(source.path) or row["size"] != source.size or row["mtime_ns"] != source.mtime_ns:
            stale += 1
    return len(discovered), stale


def command_status(conn: sqlite3.Connection, args: argparse.Namespace, cache_path: Path, codex_home: Path) -> None:
    counts = conn.execute(
        "SELECT COUNT(*) sessions, COALESCE(SUM(message_count),0) messages FROM sessions"
    ).fetchone()
    discovered, stale = stale_count(conn, codex_home)
    last = conn.execute("SELECT value FROM metadata WHERE key='last_refresh'").fetchone()
    payload = {
        "codex_home": str(codex_home),
        "cache": str(cache_path),
        "cache_size": cache_path.stat().st_size if cache_path.exists() else 0,
        "indexed_sessions": counts["sessions"],
        "indexed_messages": counts["messages"],
        "discovered_sessions": discovered,
        "stale_sessions": stale,
        "last_refresh": last[0] if last else None,
    }
    if args.format != "text":
        emit(payload, args.format, kind="status")
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def remove_cache(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.exists():
            candidate.unlink()


def validate_bounds(args: argparse.Namespace) -> None:
    if hasattr(args, "limit") and not 1 <= args.limit <= MAX_LIMIT:
        raise ReaderError(f"--limit must be between 1 and {MAX_LIMIT}")
    if hasattr(args, "excerpt_chars") and not 40 <= args.excerpt_chars <= 2000:
        raise ReaderError("--excerpt-chars must be between 40 and 2000")
    if hasattr(args, "message_chars") and not 200 <= args.message_chars <= HARD_OUTPUT_CHARS:
        raise ReaderError(f"--message-chars must be between 200 and {HARD_OUTPUT_CHARS}")
    if hasattr(args, "max_output_chars") and not 1000 <= args.max_output_chars <= HARD_OUTPUT_CHARS:
        raise ReaderError(f"--max-output-chars must be between 1000 and {HARD_OUTPUT_CHARS}")
    if (
        hasattr(args, "excerpt_chars")
        and hasattr(args, "max_output_chars")
        and args.excerpt_chars > args.max_output_chars
    ):
        raise ReaderError("--excerpt-chars cannot exceed --max-output-chars")
    if hasattr(args, "context") and not 0 <= args.context <= 10:
        raise ReaderError("--context must be between 0 and 10")
    if hasattr(args, "offset") and args.offset < 0:
        raise ReaderError("--offset must be non-negative")
    if hasattr(args, "since") and args.since and re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        args.since += "T00:00:00Z"
    if hasattr(args, "until") and args.until and re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.until):
        args.until += "T23:59:59.999999Z"


def add_common_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd", help="CWD substring (sessions) or substring filter (search)")
    parser.add_argument("--since", help="Inclusive ISO timestamp/date lower bound")
    parser.add_argument("--until", help="Inclusive ISO timestamp/date upper bound")
    parser.add_argument("--archive", choices=["both", "active", "archived"], default="both")


def add_local_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=["text", "json", "jsonl"],
        default=argparse.SUPPRESS,
        help="Output format (also accepted before the command)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", help="Codex home containing sessions and archived_sessions")
    parser.add_argument("--cache", help="SQLite cache path")
    parser.add_argument("--format", choices=["text", "json", "jsonl"], default="text")
    parser.add_argument("--no-refresh", action="store_true", help="Do not refresh before read commands")
    sub = parser.add_subparsers(dest="command", required=True)

    sessions = sub.add_parser("sessions", help="List sessions newest-first")
    sessions.add_argument("--session", help="Exact path, UUID, or unique UUID prefix")
    sessions.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    add_common_filters(sessions)
    add_local_format(sessions)

    inspect = sub.add_parser("inspect", help="Inspect one session without printing bodies")
    inspect.add_argument("session")
    add_local_format(inspect)

    show = sub.add_parser("show", help="Render a bounded logical message range")
    show.add_argument("session")
    show.add_argument("--view", choices=["conversation", "all"], default="conversation")
    show.add_argument("--range", help="N, START:END, START:, or :END (inclusive)")
    show.add_argument("--roles", help="Comma-separated user,assistant (agent is accepted)")
    show.add_argument("--phases", help="Comma-separated user,commentary,final_answer")
    show.add_argument("--message-chars", type=int, default=DEFAULT_MESSAGE_CHARS)
    show.add_argument("--max-output-chars", type=int, default=DEFAULT_OUTPUT_CHARS)
    add_local_format(show)

    search = sub.add_parser("search", help="Search canonical messages")
    search.add_argument("query")
    search.add_argument("--mode", choices=["fts", "literal", "regex"], default="fts")
    search.add_argument("--session", help="Exact path, UUID, or unique UUID prefix")
    search.add_argument("--roles", help="Comma-separated user,assistant (agent is accepted)")
    search.add_argument("--phases", help="Comma-separated user,commentary,final_answer")
    search.add_argument("--order", choices=["newest", "oldest", "rank"], default="newest")
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search.add_argument("--offset", type=int, default=0, help="Skip ordered matches for continuation")
    search.add_argument("--context", type=int, default=0)
    search.add_argument("--excerpt-chars", type=int, default=DEFAULT_EXCERPT_CHARS)
    search.add_argument("--max-output-chars", type=int, default=DEFAULT_OUTPUT_CHARS)
    search.add_argument("--ignore-case", action=argparse.BooleanOptionalAction, default=True)
    add_common_filters(search)
    add_local_format(search)

    index = sub.add_parser("index", help="Refresh the incremental cache")
    index.add_argument("--rebuild", action="store_true", help="Replace only the derived cache")
    index.add_argument("--prune", action=argparse.BooleanOptionalAction, default=True)
    add_local_format(index)

    status = sub.add_parser("status", help="Report cache coverage without refreshing")
    add_local_format(status)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_bounds(args)
        codex_home = codex_home_from(args)
        cache_path = cache_path_from(args)
        if args.command == "index" and args.rebuild:
            remove_cache(cache_path)
        conn = connect_db(cache_path)
        try:
            should_refresh = args.command == "index" or (
                args.command in {"sessions", "inspect", "show", "search"} and not args.no_refresh
            )
            refresh_stats = None
            if should_refresh:
                refresh_stats = refresh_index(
                    conn,
                    codex_home,
                    prune=getattr(args, "prune", True),
                )
            if args.command == "index":
                if args.format == "text":
                    print(" ".join(f"{key}={value}" for key, value in refresh_stats.items()))
                else:
                    emit(refresh_stats, args.format, kind="index")
            elif args.command == "sessions":
                command_sessions(conn, args)
            elif args.command == "inspect":
                command_inspect(conn, args)
            elif args.command == "show":
                command_show(conn, args)
            elif args.command == "search":
                command_search(conn, args)
            elif args.command == "status":
                command_status(conn, args, cache_path, codex_home)
        finally:
            conn.close()
        return 0
    except (ReaderError, OSError, sqlite3.DatabaseError) as exc:
        eprint(f"session-reader: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
