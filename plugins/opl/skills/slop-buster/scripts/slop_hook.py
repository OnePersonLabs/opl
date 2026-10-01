"""Fast local hook for evidence-backed slop alerts and assistant feedback."""

from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from typing import Any

from slop_catalog import CatalogError, STEERING, load_catalog, match_patterns


MAX_INPUT = 256 * 1024
REMINDER_SUFFIX = " Do not reply to this reminder itself. If the requested action is already complete, ignore this message."
MAX_MESSAGE = 16000
COOLDOWN_SECONDS = 60
MARKER = re.compile(r"^SLOP_CHECK ([a-f0-9]{16}) (true|false)$", re.MULTILINE)


def state_path() -> Path:
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / "cache" / "slop-buster" / "hooks.sqlite3"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=1.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=1000")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS alerts (
          alert_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          turn_id TEXT NOT NULL,
          pattern_id TEXT NOT NULL,
          catalog_version INTEGER NOT NULL,
          evidence_ids TEXT NOT NULL,
          event TEXT NOT NULL,
          source_path TEXT,
          source_size INTEGER,
          created_at REAL NOT NULL,
          feedback TEXT CHECK (feedback IN ('true','false')),
          feedback_at REAL
        );
        CREATE INDEX IF NOT EXISTS alerts_pending ON alerts(session_id,turn_id,feedback);
        CREATE INDEX IF NOT EXISTS alerts_cooldown ON alerts(session_id,pattern_id,created_at);
        CREATE TABLE IF NOT EXISTS alert_evidence (
          session_id TEXT NOT NULL,
          turn_id TEXT NOT NULL,
          evidence_id TEXT NOT NULL,
          alert_id TEXT NOT NULL,
          PRIMARY KEY(session_id,turn_id,evidence_id)
        );
        CREATE TABLE IF NOT EXISTS turns (
          session_id TEXT PRIMARY KEY,
          turn_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS continuations (
          session_id TEXT NOT NULL,
          turn_id TEXT NOT NULL,
          PRIMARY KEY(session_id,turn_id)
        );
        CREATE TABLE IF NOT EXISTS transcript_cursors (
          session_id TEXT PRIMARY KEY,
          path TEXT NOT NULL,
          turn_id TEXT NOT NULL,
          offset INTEGER NOT NULL
        );
    """)
    return db


def export_feedback(db_path: str | Path) -> list[dict[str, Any]]:
    """Read metadata for daily import; no prompt or response text is persisted."""
    if not Path(db_path).exists():
        return []
    with closing(sqlite3.connect(db_path, timeout=1.0)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT alert_id,session_id,turn_id,pattern_id,catalog_version,"
                          "evidence_ids,event,source_path,source_size,created_at,feedback,feedback_at "
                          "FROM alerts ORDER BY created_at,alert_id").fetchall()
        return [{**dict(row), "evidence_ids": json.loads(row["evidence_ids"])} for row in rows]


def _audit_session(data_repo: Path, session_id: str) -> bool:
    path = data_repo / ".runtime" / "audit-sessions.json"
    if not path.exists():
        return False
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Cannot read audit session registry {path}: {exc}") from exc
    if not isinstance(registry, dict) or registry.get("version") != 1 or not isinstance(registry.get("session_ids"), list):
        raise CatalogError(f"Invalid audit session registry {path}")
    return session_id in registry["session_ids"]


def _source_anchor(payload: dict[str, Any]) -> tuple[str | None, int | None]:
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None, None
    try:
        return path, Path(path).stat().st_size
    except OSError:
        return path, None


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value[:MAX_MESSAGE]
    if isinstance(value, list):
        return "\n".join(part["text"] for part in value if isinstance(part, dict) and
                         part.get("type") in {"text", "output_text"} and isinstance(part.get("text"), str))[:MAX_MESSAGE]
    return ""


def _transcript_message(record: Any) -> tuple[str, str, str, bool] | None:
    """Recognize Codex prose records; tool calls and tool output have no prose role."""
    if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
        return None
    item = record["payload"]
    if record.get("type") == "event_msg":
        if item.get("type") == "user_message" and isinstance(item.get("message"), str):
            return "user", "user", item["message"], True
        if item.get("type") == "agent_message" and isinstance(item.get("message"), str):
            phase = item.get("phase") or "final_answer"
            if phase in {"commentary", "final_answer"}:
                return "assistant", phase, item["message"][:MAX_MESSAGE], True
    if record.get("type") == "response_item" and item.get("type") == "message":
        role = item.get("role")
        if role == "user":
            return "user", "user", _extract_text(item.get("content")), False
        if role == "assistant":
            phase = item.get("phase") or "final_answer"
            if phase in {"commentary", "final_answer"}:
                return "assistant", phase, _extract_text(item.get("content")), False
    return None


def _current_assistant_prose(db: sqlite3.Connection, payload: dict[str, Any], turn_id: str) -> list[tuple[str, str]]:
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return []
    prior = db.execute("SELECT path,turn_id,offset FROM transcript_cursors WHERE session_id=?",
                       (payload["session_id"],)).fetchone()
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            end = stream.tell()
            continuing = bool(prior and prior["path"] == path and prior["turn_id"] == turn_id and
                              prior["offset"] <= end)
            start = prior["offset"] if continuing else max(0, end - 65536)
            start = max(start, end - 65536)
            stream.seek(start)
            if start and (not continuing or start != prior["offset"]):
                # A tail starting inside a line cannot create a fake prose record.
                stream.readline()
            lines = stream.readlines()
    except OSError:
        return []
    parsed: list[tuple[str, str, str, bool]] = []
    for line in lines[-128:]:
        try:
            message = _transcript_message(json.loads(line))
        except (UnicodeError, json.JSONDecodeError):
            continue
        if message:
            parsed.append(message)
    last_user = max((index for index, item in enumerate(parsed) if item[0] == "user"), default=-1)
    if not continuing and last_user < 0:
        # Without a current-turn boundary, tail prose might belong to a prior turn.
        return []
    if last_user >= 0:
        parsed = parsed[last_user + 1:]
    db.execute("INSERT INTO transcript_cursors(session_id,path,turn_id,offset) VALUES(?,?,?,?) "
               "ON CONFLICT(session_id) DO UPDATE SET path=excluded.path,turn_id=excluded.turn_id,offset=excluded.offset",
               (payload["session_id"], path, turn_id, end))
    canonical = {(phase, body) for role, phase, body, is_canonical in parsed
                 if role == "assistant" and is_canonical}
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for role, phase, body, is_canonical in parsed:
        identity = (phase, body)
        if role != "assistant" or not body or identity in seen or (not is_canonical and identity in canonical):
            continue
        seen.add(identity)
        result.append(identity)
    return result


def _assistant_markers(text: str) -> dict[str, str]:
    """Accept bare assistant lines, excluding quotations and code fences."""
    found: dict[str, str] = {}
    fence = False
    for line in text.splitlines():
        if line.startswith("```") or line.startswith("~~~"):
            fence = not fence
            continue
        if fence:
            continue
        match = MARKER.fullmatch(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _turn_id(db: sqlite3.Connection, payload: dict[str, Any], event: str, text: str,
             source_size: int | None) -> str:
    explicit = payload.get("turn_id")
    if isinstance(explicit, str) and explicit:
        return explicit[:160]
    session_id = payload["session_id"]
    if event == "UserPromptSubmit":
        anchor = f"{session_id}\0{text}\0{source_size}"
        turn_id = hashlib.sha256(anchor.encode()).hexdigest()[:24]
        db.execute("INSERT INTO turns(session_id,turn_id) VALUES(?,?) "
                   "ON CONFLICT(session_id) DO UPDATE SET turn_id=excluded.turn_id", (session_id, turn_id))
        return turn_id
    row = db.execute("SELECT turn_id FROM turns WHERE session_id=?", (session_id,)).fetchone()
    return row["turn_id"] if row else session_id[:160]


def handle_event(payload: dict[str, Any], config: dict[str, Any], *, db_path: Path | None = None,
                 now: float | None = None) -> dict[str, Any] | None:
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if event not in {"UserPromptSubmit", "PreToolUse", "Stop"} or not isinstance(session_id, str) or not session_id:
        return None
    data_repo = Path(config["data_repo"])
    if _audit_session(data_repo, session_id):
        return None
    catalog = load_catalog(data_repo)
    if not catalog["detectors"]:
        return None
    prompt_text = _extract_text(payload.get("prompt")) if event == "UserPromptSubmit" else ""
    timestamp = time.time() if now is None else now
    source_path, source_size = _source_anchor(payload)
    with closing(connect(db_path or state_path())) as db, db:
        turn_id = _turn_id(db, payload, event, prompt_text, source_size)
        prose = _current_assistant_prose(db, payload, turn_id) if event != "UserPromptSubmit" else []
        direct_final = _extract_text(payload.get("last_assistant_message")) if event == "Stop" else ""
        if direct_final and ("final_answer", direct_final) not in prose:
            prose.append(("final_answer", direct_final))
        if event != "UserPromptSubmit":
            markers = {}
            for _, body in prose:
                markers.update(_assistant_markers(body))
            for alert_id, flag in markers.items():
                db.execute("UPDATE alerts SET feedback=?,feedback_at=? WHERE alert_id=? AND session_id=? "
                           "AND turn_id=? AND feedback IS NULL", (flag, timestamp, alert_id, session_id, turn_id))
        if event == "UserPromptSubmit":
            matches = match_patterns(prompt_text, "user", "user", catalog, event=event)
        else:
            phase, body = prose[-1] if prose else ("", "")
            matches = match_patterns(body, "assistant", phase, catalog, event=event)
        emitted: list[tuple[str, dict[str, Any]]] = []
        for match in matches:
            pattern_id = match["pattern_id"]
            evidence_ids = match["evidence_ids"]
            placeholders = ",".join("?" for _ in evidence_ids)
            already_evidenced = db.execute(
                f"SELECT 1 FROM alert_evidence WHERE session_id=? AND turn_id=? AND evidence_id IN ({placeholders})",
                (session_id, turn_id, *evidence_ids)).fetchone()
            if already_evidenced:
                continue
            digest = hashlib.sha256(f"{session_id}\0{turn_id}\0{pattern_id}\0{catalog['version']}".encode()).hexdigest()[:16]
            prior = db.execute("SELECT 1 FROM alerts WHERE session_id=? AND pattern_id=? AND created_at>?",
                               (session_id, pattern_id, timestamp - COOLDOWN_SECONDS)).fetchone()
            if prior:
                continue
            inserted = db.execute("INSERT OR IGNORE INTO alerts(alert_id,session_id,turn_id,pattern_id,"
                                  "catalog_version,evidence_ids,event,source_path,source_size,created_at) "
                                  "VALUES(?,?,?,?,?,?,?,?,?,?)", (digest, session_id, turn_id, pattern_id,
                                  catalog["version"], json.dumps(match["evidence_ids"]), event,
                                  source_path, source_size, timestamp)).rowcount
            if inserted:
                db.executemany("INSERT OR IGNORE INTO alert_evidence(session_id,turn_id,evidence_id,alert_id) "
                               "VALUES(?,?,?,?)", ((session_id, turn_id, evidence_id, digest)
                                                 for evidence_id in evidence_ids))
                emitted.append((digest, match))
                # One warning per event keeps every recorded alert visible to the agent.
                break
        if emitted and event != "Stop":
            notices = [f"Slop check {alert_id} ({match['pattern_id']}): {STEERING[match['steering']]} "
                       f"Report SLOP_CHECK {alert_id} true or SLOP_CHECK {alert_id} false."
                       for alert_id, match in emitted]
            warning = " ".join(notices)
            warning = warning[:600 - len(REMINDER_SUFFIX)] + REMINDER_SUFFIX
            return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": warning}}
        if event == "Stop" and not payload.get("stop_hook_active"):
            pending = db.execute("SELECT alert_id,pattern_id FROM alerts WHERE session_id=? "
                                 "AND turn_id=? AND feedback IS NULL ORDER BY created_at LIMIT 1",
                                 (session_id, turn_id)).fetchone()
            already_continued = db.execute("SELECT 1 FROM continuations WHERE session_id=? AND turn_id=?",
                                           (session_id, turn_id)).fetchone()
            if pending and not already_continued:
                db.execute("INSERT INTO continuations(session_id,turn_id) VALUES(?,?)", (session_id, turn_id))
                warning = f"Slop check {pending['alert_id']} ({pending['pattern_id']}): "
                warning += "If the warning applies, correct the response; otherwise continue. "
                warning += f"Report SLOP_CHECK {pending['alert_id']} true or SLOP_CHECK {pending['alert_id']} false."
                warning = warning[:600 - len(REMINDER_SUFFIX)] + REMINDER_SUFFIX
                return {"decision": "block", "reason": warning}
    return None


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("hook input exceeds 256 KiB")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        from slop_config import config_file, load_config
        if not os.environ.get("SLOP_BUSTER_CONFIG") and not config_file().is_file():
            return
        config = load_config()
        if not config:
            return
        result = handle_event(payload, config)
        if result:
            print(json.dumps(result))
    except (ValueError, CatalogError, OSError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        print(json.dumps({"level": "error", "operation": "slop_hook", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
