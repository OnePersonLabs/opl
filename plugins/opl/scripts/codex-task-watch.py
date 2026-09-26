#!/usr/bin/env python3
"""Observe active Codex turns and notify when they stop producing activity."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import sys
import time
from typing import Any, Callable, Sequence
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_IDLE_SECONDS = 25 * 60
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_RETRY_SECONDS = 5 * 60
METADATA_RETRY_SECONDS = 5 * 60
MAX_NTFY_MESSAGE_BYTES = 3900
MAX_STORED_RESPONSE_BYTES = 16 * 1024
ACTIVE_EVENTS = {
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "SubagentStart",
    "SubagentStop",
}
INACTIVE_EVENTS = {"Stop", "Interrupt", "SessionEnd"}


class WatchError(RuntimeError):
    """An actionable watchdog error."""


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".codex"


def state_path(home: Path | None = None) -> Path:
    return (home or codex_home()) / "codex-watch" / "state.sqlite3"


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=0.75)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 750")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            cwd TEXT NOT NULL,
            transcript_path TEXT,
            state TEXT NOT NULL CHECK (state IN ('active', 'inactive')),
            last_activity REAL NOT NULL,
            last_event TEXT NOT NULL,
            last_assistant_message TEXT,
            rollout_size INTEGER,
            rollout_mtime_ns INTEGER,
            alert_sent INTEGER NOT NULL DEFAULT 0,
            next_notify_at REAL,
            display_name TEXT,
            preview TEXT,
            metadata_checked_at REAL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_state_activity
            ON sessions(state, last_activity);
        """
    )
    connection.commit()
    with contextlib.suppress(PermissionError):
        path.chmod(0o600)
    return connection


def file_signature(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, str) or not value:
        return None, None
    try:
        stat = Path(value).stat()
    except (FileNotFoundError, OSError):
        return None, None
    return stat.st_size, stat.st_mtime_ns


def record_hook_event(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    now: float | None = None,
) -> bool:
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if event not in ACTIVE_EVENTS | INACTIVE_EVENTS:
        return False
    if not isinstance(session_id, str) or not session_id.strip():
        raise WatchError("hook input is missing session_id")
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    transcript = payload.get("transcript_path")
    transcript = transcript if isinstance(transcript, str) and transcript else None
    timestamp = time.time() if now is None else now
    size, mtime_ns = file_signature(transcript)
    active = event in ACTIVE_EVENTS
    assistant = payload.get("last_assistant_message") if event == "Stop" else None
    assistant = assistant if isinstance(assistant, str) and assistant.strip() else None
    if assistant:
        assistant = truncate_utf8(assistant, MAX_STORED_RESPONSE_BYTES)

    connection.execute(
        """
        INSERT INTO sessions(
            session_id, cwd, transcript_path, state, last_activity, last_event,
            last_assistant_message, rollout_size, rollout_mtime_ns, alert_sent,
            next_notify_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            cwd = excluded.cwd,
            transcript_path = COALESCE(excluded.transcript_path, sessions.transcript_path),
            state = excluded.state,
            last_activity = CASE
                WHEN excluded.state = 'active' THEN excluded.last_activity
                ELSE sessions.last_activity
            END,
            last_event = excluded.last_event,
            last_assistant_message = COALESCE(
                excluded.last_assistant_message, sessions.last_assistant_message
            ),
            rollout_size = COALESCE(excluded.rollout_size, sessions.rollout_size),
            rollout_mtime_ns = COALESCE(excluded.rollout_mtime_ns, sessions.rollout_mtime_ns),
            alert_sent = CASE WHEN excluded.state = 'active' THEN 0 ELSE sessions.alert_sent END,
            next_notify_at = CASE WHEN excluded.state = 'active' THEN NULL ELSE sessions.next_notify_at END,
            updated_at = excluded.updated_at
        """,
        (
            session_id,
            cwd,
            transcript,
            "active" if active else "inactive",
            timestamp,
            event,
            assistant,
            size,
            mtime_ns,
            timestamp,
        ),
    )
    connection.commit()
    return True


def refresh_rollout_activity(
    connection: sqlite3.Connection,
    *,
    now: float | None = None,
) -> int:
    timestamp = time.time() if now is None else now
    changed = 0
    rows = connection.execute(
        "SELECT session_id, transcript_path, rollout_size, rollout_mtime_ns FROM sessions WHERE state='active'"
    ).fetchall()
    for row in rows:
        size, mtime_ns = file_signature(row["transcript_path"])
        if size is None:
            continue
        old_size, old_mtime = row["rollout_size"], row["rollout_mtime_ns"]
        if old_size is None or old_mtime is None:
            connection.execute(
                "UPDATE sessions SET rollout_size=?, rollout_mtime_ns=?, updated_at=? WHERE session_id=?",
                (size, mtime_ns, timestamp, row["session_id"]),
            )
            continue
        if size == old_size and mtime_ns == old_mtime:
            continue
        connection.execute(
            """
            UPDATE sessions
            SET rollout_size=?, rollout_mtime_ns=?, last_activity=?, last_event='RolloutGrowth',
                alert_sent=0, next_notify_at=NULL, updated_at=?
            WHERE session_id=? AND state='active'
            """,
            (size, mtime_ns, timestamp, timestamp, row["session_id"]),
        )
        changed += 1
    connection.commit()
    return changed


def parse_duration(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    normalized = value.strip().lower()
    if len(normalized) < 2 or normalized[-1] not in units:
        raise argparse.ArgumentTypeError("duration must end in s, m, h, or d")
    try:
        amount = float(normalized[:-1])
    except ValueError as error:
        raise argparse.ArgumentTypeError("duration must contain a number") from error
    if not math.isfinite(amount) or amount <= 0:
        raise argparse.ArgumentTypeError("duration must be finite and positive")
    seconds = amount * units[normalized[-1]]
    if not math.isfinite(seconds):
        raise argparse.ArgumentTypeError("duration is too large")
    return seconds


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds}s"


def project_name(cwd: str) -> str:
    return Path(cwd).name or cwd


def fallback_name(row: sqlite3.Row | dict[str, Any]) -> str:
    return f"{project_name(row['cwd'])} ({row['session_id'][:8]})"


class MetadataResolver:
    """Resolve persisted names through the official read-only app-server API."""

    def __init__(self, cwd: Path, timeout: float = 8.0):
        try:
            import opl_codex_inventory as inventory
        except ImportError as error:
            raise WatchError("Codex metadata helper is unavailable") from error
        self._inventory = inventory
        self._timeout = timeout
        environment = os.environ.copy()
        self._server = inventory._AppServer(inventory._command(), cwd, environment)
        self._server.request(
            "initialize",
            {"clientInfo": {"name": "opl-codex-watch", "title": "OPL Codex Watch", "version": "1"}},
            timeout,
        )
        self._server.send({"method": "initialized", "params": {}})

    def read(self, session_id: str) -> tuple[str | None, str | None]:
        result = self._server.request(
            "thread/read", {"threadId": session_id, "includeTurns": False}, self._timeout
        )
        thread = result.get("thread") if isinstance(result, dict) else None
        if not isinstance(thread, dict):
            raise WatchError("Codex thread/read returned malformed metadata")
        name = thread.get("name")
        preview = thread.get("preview")
        return (
            name.strip() if isinstance(name, str) and name.strip() else None,
            preview.strip() if isinstance(preview, str) and preview.strip() else None,
        )

    def close(self) -> None:
        self._server.close()

    def __enter__(self) -> "MetadataResolver":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def resolve_missing_metadata(
    connection: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
    *,
    resolver_factory: Callable[[Path], Any] = MetadataResolver,
    now: float | None = None,
) -> None:
    timestamp = time.time() if now is None else now
    missing = [
        row
        for row in rows
        if not row["display_name"]
        and not row["preview"]
        and (
            row["metadata_checked_at"] is None
            or row["metadata_checked_at"] <= timestamp - METADATA_RETRY_SECONDS
        )
    ]
    if not missing:
        return
    try:
        resolver = resolver_factory(Path(missing[0]["cwd"]))
    except Exception as error:  # Metadata is optional; surface the exact degraded mode.
        eprint(f"WARN codex-watch metadata unavailable: {error}")
        connection.executemany(
            "UPDATE sessions SET metadata_checked_at=? WHERE session_id=?",
            [(timestamp, row["session_id"]) for row in missing],
        )
        connection.commit()
        return
    try:
        for row in missing:
            try:
                name, preview = resolver.read(row["session_id"])
            except Exception as error:
                eprint(f"WARN codex-watch metadata failed session={row['session_id'][:8]} error={error}")
                connection.execute(
                    "UPDATE sessions SET metadata_checked_at=? WHERE session_id=?",
                    (timestamp, row["session_id"]),
                )
                # Do not retain a write lock while resolving the next thread.
                connection.commit()
                continue
            connection.execute(
                "UPDATE sessions SET display_name=?, preview=?, metadata_checked_at=? WHERE session_id=?",
                (name, preview, timestamp, row["session_id"]),
            )
            # The next resolver.read() may need its own database connection.
            connection.commit()
        connection.commit()
    finally:
        resolver.close()


def session_name(row: sqlite3.Row | dict[str, Any]) -> str:
    return row["display_name"] or row["preview"] or fallback_name(row)


def truncate_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    suffix = "\n...[truncated]"
    budget = max(0, limit - len(suffix.encode("utf-8")))
    prefix = encoded[:budget]
    while prefix:
        try:
            return prefix.decode("utf-8") + suffix
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    return suffix.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def ntfy_target(url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise WatchError("CODEX_WATCH_NTFY_URL must be a full HTTPS topic URL")
    segments = [urllib.parse.unquote(item) for item in parsed.path.split("/") if item]
    if not segments:
        raise WatchError("CODEX_WATCH_NTFY_URL must include a topic")
    topic = segments[-1]
    parent = "/" + "/".join(urllib.parse.quote(item, safe="") for item in segments[:-1])
    publish_path = (parent.rstrip("/") + "/") if parent != "/" else "/"
    endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, publish_path, "", ""))
    return endpoint, topic


def send_ntfy(
    url: str,
    token: str | None,
    title: str,
    message: str,
    *,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    endpoint, topic = ntfy_target(url)
    payload = json.dumps(
        {"topic": topic, "title": title, "message": truncate_utf8(message, MAX_NTFY_MESSAGE_BYTES)},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with opener(request, timeout=10) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise WatchError(f"ntfy returned HTTP {status}")
            return
        except urllib.error.HTTPError as error:
            last_error = error
            transient = error.code == 429 or error.code >= 500
            if not transient:
                raise WatchError(f"ntfy rejected the notification with HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError, WatchError) as error:
            last_error = error
        if attempt + 1 < attempts:
            delay = (2**attempt) + random.random()
            eprint(f"WARN codex-watch ntfy retry={attempt + 1} delay={delay:.1f}s error={type(last_error).__name__}")
            sleep(delay)
    raise WatchError(f"ntfy delivery failed after {attempts} attempts: {type(last_error).__name__}") from last_error


def notification_body(row: sqlite3.Row | dict[str, Any], silence: float) -> str:
    parts = [
        f"Project: {project_name(row['cwd'])}",
        f"Session: {session_name(row)}",
        f"Thread: {row['session_id'][:8]}",
        f"Silent: {format_duration(silence)}",
    ]
    if row["last_assistant_message"]:
        parts.extend(("", "Last completed agent response:", row["last_assistant_message"]))
    return truncate_utf8("\n".join(parts), MAX_NTFY_MESSAGE_BYTES)


def due_sessions(connection: sqlite3.Connection, idle: float, now: float) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM sessions
        WHERE state='active'
          AND alert_sent=0
          AND (? - last_activity) >= ?
          AND (next_notify_at IS NULL OR next_notify_at <= ?)
        ORDER BY last_activity ASC
        """,
        (now, idle, now),
    ).fetchall()


def deliver_due_notifications(
    connection: sqlite3.Connection,
    *,
    idle: float,
    url: str,
    token: str | None,
    now: float | None = None,
    sender: Callable[[str, str | None, str, str], None] = send_ntfy,
) -> tuple[int, int]:
    timestamp = time.time() if now is None else now
    sent = failed = 0
    for row in due_sessions(connection, idle, timestamp):
        silence = timestamp - row["last_activity"]
        try:
            sender(url, token, f"Codex task silent for {format_duration(idle)}", notification_body(row, silence))
        except Exception as error:
            failed += 1
            connection.execute(
                """
                UPDATE sessions SET next_notify_at=?, updated_at=?
                WHERE session_id=? AND state='active' AND alert_sent=0
                  AND last_activity=? AND updated_at=?
                """,
                (
                    timestamp + DEFAULT_RETRY_SECONDS,
                    timestamp,
                    row["session_id"],
                    row["last_activity"],
                    row["updated_at"],
                ),
            )
            eprint(
                f"ERROR codex-watch notification session={row['session_id'][:8]} "
                f"error={type(error).__name__}"
            )
            # Do not retain a write lock while delivering the next notification.
            connection.commit()
        else:
            sent += 1
            connection.execute(
                """
                UPDATE sessions SET alert_sent=1, next_notify_at=NULL, updated_at=?
                WHERE session_id=? AND state='active' AND alert_sent=0
                  AND last_activity=? AND updated_at=?
                """,
                (timestamp, row["session_id"], row["last_activity"], row["updated_at"]),
            )
            # The next sender call may record fresh lifecycle activity.
            connection.commit()
    connection.commit()
    return sent, failed


def fetch_sessions(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT * FROM sessions ORDER BY state='active' DESC, last_activity DESC"
    ).fetchall()


def session_payload(row: sqlite3.Row, idle: float, now: float) -> dict[str, Any]:
    silence = max(0.0, now - row["last_activity"])
    return {
        "session_id": row["session_id"],
        "project": project_name(row["cwd"]),
        "name": session_name(row),
        "state": row["state"],
        "last_event": row["last_event"],
        "silent_seconds": int(silence),
        "remaining_seconds": max(0, int(idle - silence)) if row["state"] == "active" else None,
        "alert_sent": bool(row["alert_sent"]),
    }


def render_status(rows: Sequence[sqlite3.Row], idle: float, now: float) -> str:
    if not rows:
        return "No observed Codex sessions."
    lines = [f"{'STATE':8} {'PROJECT':24} {'SESSION':36} {'SILENT':10} {'REMAINING':10}"]
    for row in rows:
        payload = session_payload(row, idle, now)
        remaining = format_duration(payload["remaining_seconds"]) if payload["remaining_seconds"] is not None else "-"
        lines.append(
            f"{payload['state'][:8]:8} {payload['project'][:24]:24} {payload['name'][:36]:36} "
            f"{format_duration(payload['silent_seconds']):10} {remaining:10}"
        )
    return "\n".join(lines)


def require_ntfy_url() -> str:
    value = os.environ.get("CODEX_WATCH_NTFY_URL")
    if not value:
        raise WatchError("CODEX_WATCH_NTFY_URL is required")
    ntfy_target(value)
    return value


def command_hook(args: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise WatchError("hook input must be a JSON object")
        connection = connect_db(args.state)
        try:
            record_hook_event(connection, payload)
        finally:
            connection.close()
    except (json.JSONDecodeError, UnicodeError, OSError, sqlite3.Error, WatchError) as error:
        # An observational hook must never prevent Codex work.
        eprint(f"WARN codex-watch hook ignored error={error}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    connection = connect_db(args.state)
    try:
        rows = fetch_sessions(connection)
        resolve_missing_metadata(connection, rows)
        rows = fetch_sessions(connection)
        now = time.time()
        if args.json:
            print(json.dumps([session_payload(row, args.idle, now) for row in rows], indent=2))
        else:
            print(render_status(rows, args.idle, now))
    finally:
        connection.close()
    return 0


def command_run(args: argparse.Namespace) -> int:
    url = require_ntfy_url()
    token = os.environ.get("CODEX_WATCH_NTFY_TOKEN")
    connection = connect_db(args.state)
    try:
        while True:
            now = time.time()
            refresh_rollout_activity(connection, now=now)
            rows = fetch_sessions(connection)
            resolve_missing_metadata(connection, rows)
            deliver_due_notifications(connection, idle=args.idle, url=url, token=token, now=now)
            rows = fetch_sessions(connection)
            if sys.stdout.isatty():
                print("\x1b[2J\x1b[H", end="")
            print(render_status(rows, args.idle, now), flush=True)
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nCodex watchdog stopped.")
    finally:
        connection.close()
    return 0


def command_test_notification(_args: argparse.Namespace) -> int:
    url = require_ntfy_url()
    send_ntfy(
        url,
        os.environ.get("CODEX_WATCH_NTFY_TOKEN"),
        "Codex watchdog test",
        "The Codex task watchdog can reach this ntfy topic.",
    )
    print("Test notification sent.")
    return 0


def command_prune(args: argparse.Namespace) -> int:
    connection = connect_db(args.state)
    try:
        cutoff = time.time() - args.older_than
        cursor = connection.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        connection.commit()
        print(f"Pruned {cursor.rowcount} session record(s).")
    finally:
        connection.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=state_path(), help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook = subparsers.add_parser("hook", help="record a lifecycle event (internal)")
    hook.set_defaults(handler=command_hook)

    run = subparsers.add_parser("run", help="run the foreground watchdog")
    run.add_argument("--idle", type=parse_duration, default=DEFAULT_IDLE_SECONDS)
    run.add_argument("--poll", type=parse_duration, default=DEFAULT_POLL_SECONDS)
    run.set_defaults(handler=command_run)

    status = subparsers.add_parser("status", help="show observed sessions")
    status.add_argument("--idle", type=parse_duration, default=DEFAULT_IDLE_SECONDS)
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=command_status)

    test_notification = subparsers.add_parser("test-notification", help="send a test ntfy alert")
    test_notification.set_defaults(handler=command_test_notification)

    prune = subparsers.add_parser("prune", help="delete stale session records")
    prune.add_argument("--older-than", type=parse_duration, default=30 * 86400)
    prune.set_defaults(handler=command_prune)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.state = args.state.expanduser().resolve()
    try:
        return args.handler(args)
    except (OSError, sqlite3.Error, WatchError) as error:
        eprint(f"codex-watch: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
