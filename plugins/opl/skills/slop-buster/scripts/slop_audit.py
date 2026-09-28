#!/usr/bin/env python3
"""Persistent, bounded audit work queue for canonical Codex session prose."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Sequence


SCRIPTS = Path(__file__).resolve().parent
READER_PATH = SCRIPTS.parent.parent / "session-reader" / "scripts" / "session_reader.py"
DEFAULT_PACKET_CHARS = 24000
PART_CHARS = 8000
CLAIM_SECONDS = 1800


class AuditError(RuntimeError):
    """A recoverable command error with a specific remedy."""


def _reader():
    spec = importlib.util.spec_from_file_location("slop_session_reader", READER_PATH)
    if spec is None or spec.loader is None:
        raise AuditError(f"Cannot load session reader at {READER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _module(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return __import__(name)


def _utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _date(value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return _iso(parsed)
    except ValueError as exc:
        raise AuditError(f"Expected timezone-aware ISO timestamp: {value}") from exc


def _config(path: str | None) -> dict[str, Any]:
    config = _module("slop_config").load_config(path)
    if not isinstance(config, dict) or not config.get("data_repo") or not config.get("source_homes"):
        raise AuditError("Configuration requires data_repo and source_homes")
    return config


def _paths(config: dict[str, Any]) -> tuple[Path, Path]:
    repo = Path(config["data_repo"]).expanduser().resolve()
    runtime = repo / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return repo, runtime


def _connect(repo: Path) -> sqlite3.Connection:
    path = repo / ".runtime" / "audit.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, since TEXT NOT NULL,
            until TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('prepared','complete'))
        );
        CREATE TABLE IF NOT EXISTS audit_sessions (session_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS hook_feedback (
            alert_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
            pattern_id TEXT NOT NULL, catalog_version INTEGER NOT NULL,
            evidence_ids_json TEXT NOT NULL, event TEXT NOT NULL,
            source_path TEXT, source_size INTEGER, created_at REAL NOT NULL,
            feedback TEXT, feedback_at REAL, host_db TEXT NOT NULL,
            audit_owned INTEGER NOT NULL, imported_at TEXT NOT NULL,
            reviewed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS hook_feedback_pattern ON hook_feedback(pattern_id,catalog_version);
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            content_fingerprint TEXT NOT NULL, occurrence INTEGER NOT NULL,
            message_no INTEGER NOT NULL, path TEXT NOT NULL, raw_line INTEGER NOT NULL,
            byte_offset INTEGER NOT NULL, timestamp TEXT NOT NULL, role TEXT NOT NULL,
            phase TEXT NOT NULL, source TEXT NOT NULL, body TEXT NOT NULL,
            source_valid INTEGER NOT NULL DEFAULT 1, invalidated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS events_session ON events(session_id);
        CREATE INDEX IF NOT EXISTS events_next_user ON events(session_id,message_no,role);
        CREATE TABLE IF NOT EXISTS scans (
            mode TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES events(event_id),
            run_id TEXT NOT NULL REFERENCES runs(run_id), matched INTEGER NOT NULL,
            PRIMARY KEY(mode,event_id)
        );
        CREATE TABLE IF NOT EXISTS source_gaps (
            run_id TEXT NOT NULL REFERENCES runs(run_id), source_key TEXT NOT NULL,
            path TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('missing_home','malformed','partial_tail')),
            count INTEGER NOT NULL, PRIMARY KEY(run_id,source_key,kind)
        );
        CREATE TABLE IF NOT EXISTS known_sources (
            session_id TEXT PRIMARY KEY, path TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS missing_sources (
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            session_id TEXT NOT NULL, last_path TEXT NOT NULL,
            PRIMARY KEY(run_id,session_id)
        );
        CREATE TABLE IF NOT EXISTS run_events (
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            event_id TEXT NOT NULL,
            PRIMARY KEY(run_id,event_id)
        );
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY, mode TEXT NOT NULL, event_id TEXT NOT NULL
                REFERENCES events(event_id), part INTEGER NOT NULL, start_char INTEGER NOT NULL,
            end_char INTEGER NOT NULL, matches_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','claimed','complete','superseded')),
            batch_id TEXT, verdict TEXT,
            UNIQUE(mode,event_id,part)
        );
        CREATE INDEX IF NOT EXISTS chunks_queue ON chunks(mode,state,chunk_id);
        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
            worker_id TEXT NOT NULL, claimed_at TEXT NOT NULL, lease_until TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('claimed','complete')),
            report_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id),
            pattern_id TEXT, category TEXT NOT NULL, severity TEXT NOT NULL,
            explanation TEXT NOT NULL, quote TEXT NOT NULL, user_summary TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS incidents_chunk ON incidents(chunk_id);
    """)
    # Source-first upgrades must open a ledger created by an earlier local run.
    for table, additions in {
        "batches": {"report_hash": "TEXT"},
        "events": {"source_valid": "INTEGER NOT NULL DEFAULT 1", "invalidated_at": "TEXT"},
        "hook_feedback": {"reviewed_at": "TEXT"},
    }.items():
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, declaration in additions.items():
            if column not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    return conn


def _registry(repo: Path) -> set[str]:
    path = repo / ".runtime" / "audit-sessions.json"
    if not path.exists():
        return set()
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict) or content.get("version") != 1 or not isinstance(content.get("session_ids"), list):
        raise AuditError(f"Invalid audit session registry: {path}")
    if any(not isinstance(item, str) for item in content["session_ids"]):
        raise AuditError(f"Invalid session ID in audit registry: {path}")
    return set(content["session_ids"])


def register_session(repo: Path, session_id: str) -> dict[str, Any]:
    if not isinstance(session_id, str) or not session_id.strip():
        raise AuditError("--session-id must be nonempty")
    normalized = session_id.strip().lower()
    path = repo / ".runtime" / "audit-sessions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    conn = _connect(repo)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for existing in _registry(repo):
            conn.execute("INSERT OR IGNORE INTO audit_sessions VALUES(?)", (existing,))
        conn.execute("INSERT OR IGNORE INTO audit_sessions VALUES(?)", (normalized,))
        ids = [row[0] for row in conn.execute("SELECT session_id FROM audit_sessions ORDER BY session_id")]
        temp.write_text(json.dumps({"version": 1, "session_ids": ids}, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
        conn.execute("COMMIT")
    except (OSError, sqlite3.DatabaseError, AuditError, ValueError):
        conn.execute("ROLLBACK")
        if temp.exists():
            temp.unlink()
        raise
    finally:
        conn.close()
    return {"registered": normalized, "count": len(ids), "path": str(path)}


def feedback_summary(conn: sqlite3.Connection, *, after: str = "", limit: int = 50) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise AuditError("--limit must be between 1 and 200")
    counts = conn.execute("""SELECT COUNT(*) total,
        SUM(CASE WHEN feedback='true' THEN 1 ELSE 0 END) confirmed,
        SUM(CASE WHEN feedback='false' THEN 1 ELSE 0 END) rejected,
        SUM(CASE WHEN feedback IS NULL THEN 1 ELSE 0 END) unrated,
        SUM(audit_owned) audit_owned,
        SUM(CASE WHEN feedback IS NOT NULL AND reviewed_at IS NULL AND audit_owned=0
                 THEN 1 ELSE 0 END) pending_review FROM hook_feedback""").fetchone()
    groups = conn.execute("""SELECT pattern_id,catalog_version,COUNT(*) count,
        SUM(CASE WHEN feedback='true' THEN 1 ELSE 0 END) confirmed,
        SUM(CASE WHEN feedback='false' THEN 1 ELSE 0 END) rejected
        FROM hook_feedback WHERE audit_owned=0 GROUP BY pattern_id,catalog_version
        ORDER BY count DESC,pattern_id,catalog_version""").fetchall()
    rows = conn.execute("""SELECT alert_id,session_id,turn_id,pattern_id,catalog_version,
        evidence_ids_json,event,source_path,source_size,created_at,feedback,feedback_at,
        host_db,audit_owned FROM hook_feedback WHERE alert_id>? ORDER BY alert_id LIMIT ?""",
        (after, limit + 1)).fetchall()
    page = rows[:limit]
    items = [{**dict(row), "evidence_ids": json.loads(row["evidence_ids_json"])} for row in page]
    for item in items:
        del item["evidence_ids_json"]
    return {"counts": {key: counts[key] or 0 for key in counts.keys()},
            "patterns": [dict(row) for row in groups], "items": items,
            "next_after": page[-1]["alert_id"] if len(rows) > limit else None}


def import_feedback(config: dict[str, Any]) -> dict[str, Any]:
    repo, _ = _paths(config)
    hook = _module("slop_hook")
    excluded = _registry(repo)
    conn = _connect(repo)
    imported = 0
    try:
        for raw_home in config["source_homes"]:
            source = Path(raw_home).expanduser().resolve() / "cache" / "slop-buster" / "hooks.sqlite3"
            for attempt in range(1, 4):
                try:
                    alerts = hook.export_feedback(source)
                    break
                except sqlite3.OperationalError as exc:
                    print(json.dumps({"warning": "feedback_read_retry", "host_db": str(source),
                                      "attempt": attempt, "error": str(exc)}), file=sys.stderr)
                    if attempt == 3:
                        raise
                    time.sleep(0.1 * attempt)
            conn.execute("BEGIN IMMEDIATE")
            try:
                for alert in alerts:
                    if not isinstance(alert.get("evidence_ids"), list):
                        raise AuditError(f"Hook alert has invalid evidence IDs: {alert.get('alert_id')}")
                    cursor = conn.execute("""INSERT INTO hook_feedback(alert_id,session_id,turn_id,
                        pattern_id,catalog_version,evidence_ids_json,event,source_path,source_size,
                        created_at,feedback,feedback_at,host_db,audit_owned,imported_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(alert_id) DO UPDATE SET feedback=excluded.feedback,
                        feedback_at=excluded.feedback_at,audit_owned=excluded.audit_owned,
                        imported_at=excluded.imported_at,
                        reviewed_at=CASE WHEN hook_feedback.feedback IS NOT excluded.feedback
                            OR hook_feedback.feedback_at IS NOT excluded.feedback_at
                            THEN NULL ELSE hook_feedback.reviewed_at END""", (
                        alert["alert_id"], alert["session_id"], alert["turn_id"],
                        alert["pattern_id"], alert["catalog_version"],
                        json.dumps(alert["evidence_ids"], ensure_ascii=False), alert["event"],
                        alert["source_path"], alert["source_size"], alert["created_at"],
                        alert["feedback"], alert["feedback_at"], str(source),
                        int(alert["session_id"] in excluded), _iso(_utc()),
                    ))
                    imported += cursor.rowcount
                conn.execute("COMMIT")
            except (sqlite3.DatabaseError, AuditError, KeyError, TypeError, ValueError):
                conn.execute("ROLLBACK")
                raise
        summary = feedback_summary(conn)
        summary["imported_or_updated"] = imported
        return summary
    finally:
        conn.close()


def acknowledge_feedback(conn: sqlite3.Connection, alert_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT alert_id,feedback,audit_owned FROM hook_feedback WHERE alert_id=?",
                       (alert_id,)).fetchone()
    if row is None or row["feedback"] is None or row["audit_owned"]:
        raise AuditError("Feedback alert is absent, unrated, or audit-owned")
    conn.execute("UPDATE hook_feedback SET reviewed_at=? WHERE alert_id=?", (_iso(_utc()), alert_id))
    summary = feedback_summary(conn)
    summary["acknowledged"] = alert_id
    return summary


def _sources(reader: Any, homes: list[str]) -> list[tuple[Path, Any]]:
    chosen: dict[str, tuple[Path, Any]] = {}
    for raw_home in homes:
        home = Path(raw_home).expanduser().resolve()
        for session_id, source in reader.discover_sources(home).items():
            previous = chosen.get(session_id)
            rank = (source.size, not source.archived, source.mtime_ns, str(source.path))
            if previous is None or rank > (
                previous[1].size, not previous[1].archived,
                previous[1].mtime_ns, str(previous[1].path),
            ):
                chosen[session_id] = (home, source)
    return list(chosen.values())


def _claude_file(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".jsonl":
        return False
    with path.open("rb") as handle:
        for _ in range(128):
            raw = handle.readline()
            if not raw:
                break
            try:
                item = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(item, dict) and item.get("type") in {"user", "assistant"}:
                return isinstance(item.get("message"), dict)
    return False


def _chunk_id(mode: str, event_id: str, part: int) -> str:
    return hashlib.sha256(f"{mode}:{event_id}:{part}".encode("ascii")).hexdigest()


def _stage(conn: sqlite3.Connection, mode: str, event: dict[str, Any], matches: list[dict], run_id: str) -> tuple[int, int]:
    conn.execute("""INSERT INTO events(event_id,session_id,content_fingerprint,occurrence,
        message_no,path,raw_line,byte_offset,timestamp,role,phase,source,body)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET
        path=excluded.path,raw_line=excluded.raw_line,byte_offset=excluded.byte_offset,
        message_no=excluded.message_no,source_valid=1,invalidated_at=NULL""", (
        event["event_id"], event["session_id"], event["content_fingerprint"],
        event["occurrence"], event["message_no"], event["path"], event["raw_line"],
        event["byte_offset"], event["timestamp"], event["role"], event["phase"],
        event["source"], event["text"],
    ))
    cursor = conn.execute("INSERT OR IGNORE INTO scans(mode,event_id,run_id,matched) VALUES(?,?,?,?)",
                          (mode, event["event_id"], run_id, int(bool(matches))))
    if cursor.rowcount == 0 or (mode == "filtered" and not matches):
        return cursor.rowcount, 0
    count = 0
    for part, start in enumerate(range(0, max(1, len(event["text"])), PART_CHARS)):
        end = min(start + PART_CHARS, len(event["text"]))
        conn.execute("""INSERT INTO chunks(chunk_id,mode,event_id,part,start_char,end_char,
            matches_json,state) VALUES(?,?,?,?,?,?,?,'pending')""", (
            _chunk_id(mode, event["event_id"], part), mode, event["event_id"],
            part, start, end, json.dumps(matches, ensure_ascii=False),
        ))
        count += 1
    return 1, count


def prepare(config: dict[str, Any], *, mode: str, since: str | None = None,
            until: str | None = None, reason: str = "", session: str | None = None) -> dict[str, Any]:
    if mode not in {"full", "filtered"}:
        raise AuditError("mode must be full or filtered")
    repo, runtime = _paths(config)
    feedback_counts = import_feedback(config)["counts"]
    reader = _reader()
    upper = _date(until) if until else _iso(_utc())
    conn = _connect(repo)
    try:
        baseline = conn.execute("SELECT MIN(since) FROM runs WHERE mode='full' AND status='complete'").fetchone()[0]
    finally:
        conn.close()
    lower = _date(since) if since else (
        _iso(dt.datetime.fromisoformat(upper.replace("Z", "+00:00")) - dt.timedelta(days=30))
        if mode == "full" or baseline is None else baseline
    )
    if lower > upper:
        raise AuditError("--since must not follow --until")
    catalog = _module("slop_catalog").load_catalog(repo) if mode == "filtered" else None
    match_patterns = _module("slop_catalog").match_patterns if mode == "filtered" else None
    selected_path = Path(session).expanduser().resolve() if session else None
    claude_path = selected_path if selected_path and _claude_file(selected_path) else None
    missing_homes = [] if claude_path else [Path(raw).expanduser().resolve()
                                            for raw in config["source_homes"]
                                            if not Path(raw).expanduser().resolve().is_dir()]
    sources = [] if claude_path else _sources(reader, config["source_homes"])
    if session:
        if claude_path is None:
            matches = [(home, source) for home, source in sources
                       if source.session_id == session.lower() or str(source.path) == session
                       or source.session_id.startswith(session.lower())]
            if len(matches) != 1:
                raise AuditError(f"Session selector must identify exactly one source: {session} ({len(matches)} matches)")
            sources = matches
    excluded = _registry(repo)
    conn = _connect(repo)
    scanned = staged = 0
    try:
        old = conn.execute("""SELECT * FROM runs WHERE mode=? AND status='prepared'
            AND reason=? ORDER BY created_at DESC LIMIT 1""", (mode, reason)).fetchone()
        if old is not None and (since is None or old["since"] == lower) and (until is None or old["until"] == upper) and session is None:
            run_id, lower, upper = old["run_id"], old["since"], old["until"]
        else:
            run_id = uuid.uuid4().hex
            conn.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                         (run_id, mode, lower, upper, reason, _iso(_utc()), "prepared"))
        scan_mode = f"full:{run_id}" if mode == "full" else mode
        for missing in missing_homes:
            conn.execute("""INSERT INTO source_gaps VALUES(?,?,?,?,1)
                ON CONFLICT(run_id,source_key,kind) DO UPDATE SET path=excluded.path,count=1""",
                (run_id, f"home:{missing}", str(missing), "missing_home"))
        for raw_home in config["source_homes"]:
            home_path = Path(raw_home).expanduser().resolve()
            if home_path.is_dir():
                conn.execute("DELETE FROM source_gaps WHERE run_id=? AND source_key=? AND kind='missing_home'",
                             (run_id, f"home:{home_path}"))
        if mode == "filtered" and baseline is None:
            conn.execute("UPDATE runs SET status='complete' WHERE run_id=?", (run_id,))
            return {"run_id": run_id, "mode": mode, "since": lower, "until": upper,
                    "indexed": 0, "staged": 0, "discovery_required": True,
                    "feedback_counts": feedback_counts,
                    "progress": progress(conn, run_id)}
        selected = {source.session_id: source for _, source in sources if source.session_id not in excluded}
        if claude_path is None:
            for known in conn.execute("SELECT session_id,path FROM known_sources"):
                if known["session_id"] in excluded:
                    conn.execute("DELETE FROM known_sources WHERE session_id=?", (known["session_id"],))
                    conn.execute("DELETE FROM missing_sources WHERE run_id=? AND session_id=?",
                                 (run_id, known["session_id"]))
                    continue
                if known["session_id"] not in selected:
                    conn.execute("""INSERT INTO missing_sources VALUES(?,?,?)
                        ON CONFLICT(run_id,session_id) DO UPDATE SET last_path=excluded.last_path""",
                        (run_id, known["session_id"], known["path"]))
            for session_id, source in selected.items():
                conn.execute("DELETE FROM missing_sources WHERE run_id=? AND session_id=?",
                             (run_id, session_id))
                conn.execute("""INSERT INTO known_sources VALUES(?,?)
                    ON CONFLICT(session_id) DO UPDATE SET path=excluded.path""",
                    (session_id, str(source.path)))
        homes = sorted({home for home, _ in sources}, key=str)
        for home in homes + ([claude_path] if claude_path else []):
            source_key = hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:20]
            index_path = runtime / f"reader-{source_key}.sqlite3"
            index = reader.connect_db(index_path)
            try:
                if claude_path:
                    reader.index_claude_file(index, claude_path)
                    selected[reader.claude_session_id(claude_path)] = reader.SourceFile(
                        reader.claude_session_id(claude_path), claude_path, False,
                        claude_path.stat().st_size, claude_path.stat().st_mtime_ns)
                else:
                    reader.refresh_index(index, home)
                if claude_path:
                    indexed_sources = [index.execute("SELECT * FROM sessions WHERE path=?", (str(claude_path),)).fetchone()]
                else:
                    indexed_sources = index.execute("SELECT * FROM sessions").fetchall()
                for indexed in indexed_sources:
                    if (indexed is None or indexed["session_id"] not in selected
                            or indexed["path"] != str(selected[indexed["session_id"]].path)):
                        continue
                    tail_bytes = indexed["size"] - indexed["indexed_offset"]
                    if tail_bytes < 0:
                        raise AuditError(f"Reader index exceeds source size after refresh: {indexed['path']} "
                                         f"(indexed_offset={indexed['indexed_offset']}, size={indexed['size']})")
                    for kind, count in (("malformed", indexed["malformed_count"]),
                                        ("partial_tail", tail_bytes)):
                        if count:
                            conn.execute("""INSERT INTO source_gaps VALUES(?,?,?,?,?)
                                ON CONFLICT(run_id,source_key,kind) DO UPDATE SET
                                path=excluded.path,count=excluded.count""",
                                (run_id, indexed["session_id"], indexed["path"], kind, count))
                        else:
                            conn.execute("DELETE FROM source_gaps WHERE run_id=? AND source_key=? AND kind=?",
                                         (run_id, indexed["session_id"], kind))
                    conn.execute("""DELETE FROM run_events WHERE run_id=? AND event_id IN
                        (SELECT event_id FROM events WHERE session_id=?)""", (run_id, indexed["session_id"]))
                # Each home may contain an alias. Only the winning physical path
                # contributes events; all homes still share the same audit ledger.
                for event in reader.iter_canonical_events(index):
                    source = selected.get(event["session_id"])
                    if source is None or Path(event["path"]) != source.path:
                        continue
                    if not event["timestamp"]:
                        raise AuditError(f"Canonical event has no timestamp: {event['path']}:{event['raw_line']}")
                    # Observe out-of-window identities without copying their
                    # prose into the audit store.
                    conn.execute("INSERT OR IGNORE INTO run_events VALUES(?,?)", (run_id, event["event_id"]))
                    timestamp = _date(event["timestamp"])
                    if not lower <= timestamp <= upper:
                        continue
                    full_reviewed = mode == "filtered" and conn.execute("""SELECT 1 FROM scans s
                        JOIN runs r ON r.run_id=s.run_id WHERE r.mode='full' AND s.event_id=?
                        AND r.status='complete' LIMIT 1""", (event["event_id"],)).fetchone() is not None
                    matches = (match_patterns(event["text"], event["role"], event["phase"], catalog)
                               if match_patterns and not full_reviewed else [])
                    if not isinstance(matches, list):
                        raise AuditError("Catalog matcher must return a list")
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        a, b = _stage(conn, scan_mode, event, matches, run_id)
                        conn.execute("COMMIT")
                    except (sqlite3.DatabaseError, KeyError, TypeError, ValueError):
                        conn.execute("ROLLBACK")
                        raise
                    scanned += a
                    staged += b
                for indexed in indexed_sources:
                    if (indexed is None or indexed["session_id"] not in selected
                            or indexed["path"] != str(selected[indexed["session_id"]].path)):
                        continue
                    session_id = indexed["session_id"]
                    conn.execute("""UPDATE events SET source_valid=0,invalidated_at=COALESCE(invalidated_at,?)
                        WHERE session_id=? AND event_id NOT IN
                        (SELECT event_id FROM run_events WHERE run_id=?)""",
                        (_iso(_utc()), session_id, run_id))
                    conn.execute("""UPDATE events SET source_valid=1,invalidated_at=NULL
                        WHERE session_id=? AND event_id IN
                        (SELECT event_id FROM run_events WHERE run_id=?)""", (session_id, run_id))
                    conn.execute("""UPDATE chunks SET state='superseded',verdict='source_rewritten',batch_id=NULL
                        WHERE state IN ('pending','claimed') AND event_id IN
                        (SELECT event_id FROM events WHERE session_id=? AND source_valid=0)""", (session_id,))
                    conn.execute("""UPDATE batches SET state='complete' WHERE state='claimed'
                        AND NOT EXISTS (SELECT 1 FROM chunks WHERE chunks.batch_id=batches.batch_id
                                        AND chunks.state='claimed')""")
                    invalidated = conn.execute("""SELECT i.incident_id,e.invalidated_at,e.path,e.raw_line
                        FROM incidents i JOIN chunks c USING(chunk_id) JOIN events e USING(event_id)
                        WHERE e.session_id=? AND e.source_valid=0""", (session_id,)).fetchall()
                    if invalidated:
                        evidence_dir = repo / "evidence"
                        evidence_dir.mkdir(parents=True, exist_ok=True)
                        for item in invalidated:
                            target = evidence_dir / f"{item['incident_id']}.invalidated.json"
                            temp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
                            temp.write_text(json.dumps({
                                "incident_id": item["incident_id"],
                                "invalidated_at": item["invalidated_at"],
                                "reason": "canonical source event no longer exists",
                                "former_path": item["path"], "former_raw_line": item["raw_line"],
                            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                            os.replace(temp, target)
            finally:
                index.close()
        return {"run_id": run_id, "mode": mode, "since": lower, "until": upper,
                "indexed": scanned, "staged": staged,
                "feedback_counts": feedback_counts,
                "discovery_required": mode == "filtered" and not catalog.get("detectors"),
                "progress": progress(conn, run_id)}
    finally:
        conn.close()


def progress(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        raise AuditError(f"Unknown run: {run_id}")
    scans = conn.execute("SELECT COUNT(*) FROM scans WHERE run_id=?", (run_id,)).fetchone()[0]
    rows = conn.execute("""SELECT c.state, COUNT(*) count FROM chunks c
        JOIN scans s ON s.event_id=c.event_id AND s.mode=c.mode
        WHERE s.run_id=? GROUP BY c.state""", (run_id,)).fetchall()
    states = {row["state"]: row["count"] for row in rows}
    gap_rows = conn.execute("SELECT kind,COUNT(*) sources,SUM(count) amount FROM source_gaps WHERE run_id=? GROUP BY kind",
                            (run_id,)).fetchall()
    missing_count = conn.execute("SELECT COUNT(*) FROM missing_sources WHERE run_id=?", (run_id,)).fetchone()[0]
    full_done = conn.execute("SELECT 1 FROM runs WHERE mode='full' AND status='complete' LIMIT 1").fetchone() is not None
    return {"run_id": run_id, "mode": run["mode"], "status": run["status"],
            "indexed": scans, "total": sum(states.values()),
            "pending": states.get("pending", 0), "claimed": states.get("claimed", 0),
            "completed": states.get("complete", 0),
            "superseded": states.get("superseded", 0),
            "needs_full_discovery": not full_done,
            "source_gaps": [dict(row) for row in gap_rows] +
                           ([{"kind": "missing_source", "sources": missing_count,
                              "amount": missing_count}] if missing_count else [])}


def latest_progress(conn: sqlite3.Connection) -> dict[str, Any]:
    latest = conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if latest is None:
        return {"run_id": None, "status": "uninitialized", "indexed": 0,
                "total": 0, "pending": 0, "claimed": 0, "completed": 0,
                "superseded": 0, "source_gaps": [], "needs_full_discovery": True}
    return progress(conn, latest[0])


def source_progress(conn: sqlite3.Connection, run_id: str, path: str) -> dict[str, Any]:
    run = progress(conn, run_id)
    resolved = str(Path(path).expanduser().resolve())
    indexed = conn.execute("""SELECT COUNT(*) FROM scans s JOIN events e USING(event_id)
        WHERE s.run_id=? AND e.path=?""", (run_id, resolved)).fetchone()[0]
    rows = conn.execute("""SELECT c.state,COUNT(*) count FROM chunks c
        JOIN scans s ON s.event_id=c.event_id AND s.mode=c.mode
        JOIN events e ON e.event_id=c.event_id WHERE s.run_id=? AND e.path=?
        GROUP BY c.state""", (run_id, resolved)).fetchall()
    states = {row["state"]: row["count"] for row in rows}
    return {"run_id": run_id, "mode": run["mode"], "source": resolved,
            "indexed": indexed, "total": sum(states.values()),
            "pending": states.get("pending", 0), "claimed": states.get("claimed", 0),
            "completed": states.get("complete", 0), "superseded": states.get("superseded", 0)}


def _packet(conn: sqlite3.Connection, batch_id: str) -> dict[str, Any]:
    batch = conn.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
    rows = conn.execute("""SELECT c.*,e.session_id,e.message_no,e.path,e.raw_line,
        e.byte_offset,e.timestamp,e.role,e.phase,e.body FROM chunks c
        JOIN events e USING(event_id) WHERE c.batch_id=?
        ORDER BY e.timestamp DESC,e.session_id DESC,e.message_no DESC,c.part""", (batch_id,)).fetchall()
    items = []
    for row in rows:
        next_user = conn.execute("""SELECT event_id,message_no,path,raw_line,byte_offset,
            substr(body,1,1000) excerpt FROM events WHERE session_id=? AND message_no>?
            AND role='user' ORDER BY message_no LIMIT 1""",
            (row["session_id"], row["message_no"])).fetchone()
        items.append({
            "chunk_id": row["chunk_id"], "event_id": row["event_id"], "part": row["part"],
            "start_char": row["start_char"], "end_char": row["end_char"],
            "body": row["body"][row["start_char"]:row["end_char"]],
            "session_id": row["session_id"], "message_no": row["message_no"],
            "path": row["path"], "raw_line": row["raw_line"],
            "byte_offset": row["byte_offset"], "timestamp": row["timestamp"],
            "role": row["role"], "phase": row["phase"],
            "matches": json.loads(row["matches_json"]),
            "next_user": dict(next_user) if next_user else None,
        })
    return {"run_id": batch["run_id"], "batch_id": batch_id,
            "worker_id": batch["worker_id"], "lease_until": batch["lease_until"], "items": items}


def next_batch(conn: sqlite3.Connection, run_id: str, worker_id: str = "default",
               max_chars: int = DEFAULT_PACKET_CHARS) -> dict[str, Any]:
    if not 12000 <= max_chars <= DEFAULT_PACKET_CHARS:
        raise AuditError("--max-chars must be between 12000 and 24000")
    state = progress(conn, run_id)
    if state["status"] == "complete":
        raise AuditError("Run is already complete")
    now = _iso(_utc())
    until = _iso(_utc() + dt.timedelta(seconds=CLAIM_SECONDS))
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Resume a worker's own immutable packet, including after process restart.
        existing = conn.execute("""SELECT batch_id FROM batches WHERE run_id=?
            AND worker_id=? AND state='claimed' ORDER BY claimed_at LIMIT 1""",
            (run_id, worker_id)).fetchone()
        if existing:
            conn.execute("UPDATE batches SET lease_until=? WHERE batch_id=?", (until, existing[0]))
            packet = _packet(conn, existing[0])
            if len(json.dumps(packet, ensure_ascii=False)) > max_chars:
                raise AuditError("Existing immutable packet exceeds requested --max-chars; retry with its original bound")
            conn.execute("COMMIT")
            return packet
        # Expired claims become pending; the original packet remains immutable.
        expired = conn.execute("SELECT batch_id FROM batches WHERE state='claimed' AND lease_until<?", (now,)).fetchall()
        for row in expired:
            conn.execute("UPDATE chunks SET state='pending',batch_id=NULL WHERE batch_id=? AND state='claimed'", (row[0],))
            conn.execute("UPDATE batches SET state='complete' WHERE batch_id=?", (row[0],))
        candidates = conn.execute("""SELECT c.chunk_id,c.end_char-c.start_char AS size FROM chunks c
            JOIN scans s ON s.event_id=c.event_id AND s.mode=c.mode
            JOIN events e USING(event_id) WHERE s.run_id=? AND c.state='pending'
            ORDER BY e.timestamp DESC,e.session_id DESC,e.message_no DESC,c.part""", (run_id,))
        chosen, used = [], 0
        body_budget = max_chars - 8000
        for row in candidates:
            if chosen and used + row["size"] > body_budget:
                break
            chosen.append(row["chunk_id"])
            used += row["size"]
            if used >= body_budget:
                break
        if not chosen:
            conn.execute("COMMIT")
            return {"run_id": run_id, "batch_id": None, "items": [], "progress": progress(conn, run_id)}
        batch_id = uuid.uuid4().hex
        conn.execute("""INSERT INTO batches(batch_id,run_id,worker_id,claimed_at,lease_until,state)
            VALUES(?,?,?,?,?,?)""", (batch_id, run_id, worker_id, now, until, "claimed"))
        conn.executemany("UPDATE chunks SET state='claimed',batch_id=? WHERE chunk_id=?", [(batch_id, item) for item in chosen])
        packet = _packet(conn, batch_id)
        while len(json.dumps(packet, ensure_ascii=False)) > max_chars:
            tail = chosen.pop()
            conn.execute("UPDATE chunks SET state='pending',batch_id=NULL WHERE chunk_id=?", (tail,))
            if not chosen:
                raise AuditError("One work chunk exceeds packet bound; inspect source metadata or catalog matches")
            packet = _packet(conn, batch_id)
        conn.execute("COMMIT")
        return packet
    except (sqlite3.DatabaseError, AuditError):
        conn.execute("ROLLBACK")
        raise


def record(conn: sqlite3.Connection, run_id: str, batch_id: str, report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) - {"verdicts", "incidents"}:
        raise AuditError("Input must be an object with verdicts and optional incidents")
    report_hash = hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
    batch = conn.execute("SELECT * FROM batches WHERE batch_id=? AND run_id=?", (batch_id, run_id)).fetchone()
    if batch is None:
        raise AuditError("Unknown batch for run")
    if batch["state"] == "complete":
        if batch["report_hash"] != report_hash:
            raise AuditError("Batch was completed with a different report or superseded source")
        ids = [row[0] for row in conn.execute("""SELECT i.incident_id FROM incidents i
            JOIN chunks c USING(chunk_id) WHERE c.batch_id=? ORDER BY i.incident_id""", (batch_id,))]
        return {"batch_id": batch_id, "already_committed": True,
                "incident_ids": ids, "progress": progress(conn, run_id)}
    verdicts = report.get("verdicts")
    incidents = report.get("incidents", [])
    if not isinstance(verdicts, list) or not isinstance(incidents, list):
        raise AuditError("Input must contain verdicts list and optional incidents list")
    if any(not isinstance(item, dict) or set(item) != {"chunk_id", "verdict"} for item in verdicts):
        raise AuditError("Each verdict requires only chunk_id and verdict")
    allowed_incident = {"chunk_id", "pattern_id", "category", "severity", "explanation", "quote", "user_summary"}
    if any(not isinstance(item, dict) or set(item) - allowed_incident for item in incidents):
        raise AuditError("Incident contains unsupported fields")
    expected = {row[0] for row in conn.execute("SELECT chunk_id FROM chunks WHERE batch_id=? AND state='claimed'", (batch_id,))}
    actual = [item.get("chunk_id") for item in verdicts if isinstance(item, dict)]
    if len(actual) != len(verdicts) or set(actual) != expected or len(actual) != len(expected):
        raise AuditError("Verdicts must cover every claimed chunk exactly once")
    if any(item.get("verdict") not in {"clean", "incident"} for item in verdicts):
        raise AuditError("Each verdict must be clean or incident")
    incident_chunks = [item.get("chunk_id") for item in incidents if isinstance(item, dict)]
    if len(incident_chunks) != len(incidents) or any(item not in expected for item in incident_chunks):
        raise AuditError("Every incident must reference a claimed chunk")
    for incident in incidents:
        if not all(isinstance(incident.get(key), str) and incident[key].strip()
                   for key in ("category", "severity", "explanation", "quote")):
            raise AuditError("Incidents require category, severity, explanation, and quote")
        row = conn.execute("""SELECT e.body,c.start_char,c.end_char FROM chunks c
            JOIN events e USING(event_id) WHERE c.chunk_id=?""", (incident["chunk_id"],)).fetchone()
        if incident["quote"] not in row["body"][row["start_char"]:row["end_char"]]:
            raise AuditError("Incident quote must occur verbatim inside its reviewed chunk")
        if incident.get("user_summary") is not None and not isinstance(incident["user_summary"], str):
            raise AuditError("Optional user_summary must be a string")
    incident_set = set(incident_chunks)
    if any((item["chunk_id"] in incident_set) != (item["verdict"] == "incident") for item in verdicts):
        raise AuditError("Incident verdicts and incident records must agree")
    conn.execute("BEGIN IMMEDIATE")
    incident_ids = []
    try:
        current = conn.execute("SELECT state FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        claimed = {row[0] for row in conn.execute("SELECT chunk_id FROM chunks WHERE batch_id=? AND state='claimed'", (batch_id,))}
        if current[0] != "claimed" or claimed != expected:
            raise AuditError("Batch claim changed before commit; request a new packet")
        for item in verdicts:
            conn.execute("UPDATE chunks SET state='complete',verdict=? WHERE chunk_id=? AND batch_id=?",
                         (item["verdict"], item["chunk_id"], batch_id))
        for item in incidents:
            identifier = hashlib.sha256(json.dumps([
                item["chunk_id"], item.get("pattern_id"), item["category"],
                item["severity"], item["explanation"], item["quote"], item.get("user_summary"),
            ], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
            incident_ids.append(identifier)
            conn.execute("""INSERT OR IGNORE INTO incidents VALUES(?,?,?,?,?,?,?,?,?)""", (
                identifier, item["chunk_id"], item.get("pattern_id"), item["category"],
                item["severity"], item["explanation"], item["quote"],
                item.get("user_summary"), _iso(_utc()),
            ))
        conn.execute("UPDATE batches SET state='complete',report_hash=? WHERE batch_id=?",
                     (report_hash, batch_id))
        conn.execute("COMMIT")
    except (sqlite3.DatabaseError, AuditError):
        conn.execute("ROLLBACK")
        raise
    return {"batch_id": batch_id, "recorded": len(verdicts), "incidents": len(incidents),
            "incident_ids": incident_ids,
            "progress": progress(conn, run_id)}


def list_incidents(conn: sqlite3.Connection, run_id: str, *, after: str = "",
                   limit: int = 50) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise AuditError("--limit must be between 1 and 200")
    progress(conn, run_id)
    summary = conn.execute("""SELECT i.category,COUNT(*) count FROM incidents i
        JOIN chunks c USING(chunk_id) JOIN scans s ON s.event_id=c.event_id AND s.mode=c.mode
        WHERE s.run_id=? GROUP BY i.category ORDER BY count DESC,i.category""", (run_id,)).fetchall()
    rows = conn.execute("""SELECT i.incident_id,i.category,i.severity,i.pattern_id,
        e.session_id,e.message_no,e.path,e.raw_line,e.role,e.source_valid,e.invalidated_at FROM incidents i
        JOIN chunks c USING(chunk_id) JOIN events e USING(event_id)
        JOIN scans s ON s.event_id=e.event_id AND s.mode=c.mode
        WHERE s.run_id=? AND i.incident_id>? ORDER BY i.incident_id LIMIT ?""",
        (run_id, after, limit + 1)).fetchall()
    page = rows[:limit]
    return {"run_id": run_id, "summary": [dict(row) for row in summary],
            "items": [dict(row) for row in page],
            "next_after": page[-1]["incident_id"] if len(rows) > limit else None}


def show(conn: sqlite3.Connection, incident_id: str, *, start: int = 0,
         chars: int = DEFAULT_PACKET_CHARS) -> dict[str, Any]:
    if start < 0 or not 1 <= chars <= DEFAULT_PACKET_CHARS:
        raise AuditError("show requires nonnegative --start and --chars 1..24000")
    row = conn.execute("""SELECT i.*,e.session_id,e.message_no,e.path,e.raw_line,
        e.byte_offset,e.body,e.source_valid,e.invalidated_at FROM incidents i JOIN chunks c USING(chunk_id)
        JOIN events e USING(event_id) WHERE i.incident_id=?""", (incident_id,)).fetchone()
    if row is None:
        raise AuditError(f"Unknown incident: {incident_id}")
    result = {key: row[key] for key in row.keys() if key != "body"}
    result.update({"start": start, "body": row["body"][start:start + chars],
                   "next_start": start + chars if start + chars < len(row["body"]) else None,
                   "total_chars": len(row["body"])})
    return result


def show_event(conn: sqlite3.Connection, event_id: str, *, start: int = 0,
               chars: int = DEFAULT_PACKET_CHARS) -> dict[str, Any]:
    if start < 0 or not 1 <= chars <= DEFAULT_PACKET_CHARS:
        raise AuditError("show requires nonnegative --start and --chars 1..24000")
    row = conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
    if row is None:
        raise AuditError(f"Unknown event: {event_id}")
    result = {key: row[key] for key in row.keys() if key != "body"}
    result.update({"start": start, "body": row["body"][start:start + chars],
                   "next_start": start + chars if start + chars < len(row["body"]) else None,
                   "total_chars": len(row["body"])})
    for direction, operator, order in (("previous_user", "<", "DESC"), ("next_user", ">", "ASC")):
        adjacent = conn.execute(f"""SELECT event_id,message_no,path,raw_line,byte_offset
            FROM events WHERE session_id=? AND message_no {operator} ? AND role='user'
            ORDER BY message_no {order} LIMIT 1""", (row["session_id"], row["message_no"])).fetchone()
        result[direction] = dict(adjacent) if adjacent else None
    return result


def capture(conn: sqlite3.Connection, repo: Path, event_id: str, *, quote: str,
            category: str, severity: str, explanation: str,
            pattern_id: str | None = None, user_summary: str | None = None) -> dict[str, Any]:
    if not all(isinstance(value, str) and value.strip() for value in (quote, category, severity, explanation)):
        raise AuditError("Capture requires nonempty quote, category, severity, and explanation")
    row = conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
    if row is None:
        raise AuditError("Unknown event; first prepare the containing session")
    if row["role"] != "assistant":
        raise AuditError("Direct capture requires an assistant event")
    position = row["body"].find(quote)
    if position < 0:
        raise AuditError("Capture quote must occur verbatim in the assistant message")
    if len(quote) > PART_CHARS:
        raise AuditError(f"Capture quote must be at most {PART_CHARS} characters")
    start = min(position, max(0, len(row["body"]) - PART_CHARS))
    end = min(start + PART_CHARS, len(row["body"]))
    chunk_id = _chunk_id("manual", event_id, position)
    identifier = hashlib.sha256(json.dumps(
        [chunk_id, pattern_id, category, severity, explanation, quote, user_summary],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    now = _iso(_utc())
    prior = conn.execute("SELECT run_id FROM scans WHERE mode='manual' AND event_id=?", (event_id,)).fetchone()
    run_id = prior[0] if prior else uuid.uuid4().hex
    conn.execute("BEGIN IMMEDIATE")
    try:
        if prior is None:
            conn.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                         (run_id, "manual", row["timestamp"], row["timestamp"], "direct capture", now, "prepared"))
        conn.execute("INSERT OR IGNORE INTO scans VALUES(?,?,?,1)", ("manual", event_id, run_id))
        conn.execute("""INSERT OR IGNORE INTO chunks(chunk_id,mode,event_id,part,start_char,
            end_char,matches_json,state,verdict) VALUES(?,?,?,?,?,?,'[]','complete','incident')""",
            (chunk_id, "manual", event_id, position, start, end))
        conn.execute("INSERT OR IGNORE INTO incidents VALUES(?,?,?,?,?,?,?,?,?)", (
            identifier, chunk_id, pattern_id, category, severity, explanation, quote, user_summary, now,
        ))
        conn.execute("COMMIT")
    except sqlite3.DatabaseError:
        conn.execute("ROLLBACK")
        raise
    result = finish(conn, repo, run_id)
    result["incident_id"] = identifier
    return result


def finish(conn: sqlite3.Connection, repo: Path, run_id: str) -> dict[str, Any]:
    state = progress(conn, run_id)
    if state["source_gaps"]:
        raise AuditError(f"Run has unresolved source gaps: {state['source_gaps']}")
    if state["pending"] or state["claimed"]:
        raise AuditError(f"Run has unfinished chunks: {state['pending']} pending, {state['claimed']} claimed")
    evidence_dir = repo / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("""SELECT DISTINCT i.incident_id,i.chunk_id,i.pattern_id,i.category,
        i.severity,i.explanation,i.quote,i.user_summary,e.session_id,e.message_no,e.path,e.raw_line,
        e.byte_offset,e.timestamp,e.role,e.phase,e.body,e.source_valid,e.invalidated_at FROM incidents i JOIN chunks c USING(chunk_id)
        JOIN events e USING(event_id) JOIN scans s ON s.event_id=e.event_id AND s.mode=c.mode
        WHERE s.run_id=? ORDER BY i.incident_id""", (run_id,)).fetchall()
    for row in rows:
        document = {key: row[key] for key in row.keys()}
        if row["role"] == "user":
            assistant = conn.execute("""SELECT event_id,message_no,path,raw_line,byte_offset,
                timestamp,body FROM events WHERE session_id=? AND message_no<?
                AND role='assistant' ORDER BY message_no DESC LIMIT 1""",
                (row["session_id"], row["message_no"])).fetchone()
            if assistant is None:
                assistant = conn.execute("""SELECT event_id,message_no,path,raw_line,byte_offset,
                    timestamp,body FROM events WHERE session_id=? AND message_no>?
                    AND role='assistant' ORDER BY message_no LIMIT 1""",
                    (row["session_id"], row["message_no"])).fetchone()
            document["attributed_assistant"] = dict(assistant) if assistant else None
        target = evidence_dir / f"{row['incident_id']}.json"
        if not target.exists():
            temp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
            temp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temp, target)
    conn.execute("UPDATE runs SET status='complete' WHERE run_id=?", (run_id,))
    state = progress(conn, run_id)
    state.update({"evidence_count": len(rows), "evidence_dir": str(evidence_dir)})
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("SLOP_BUSTER_CONFIG"))
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--mode", choices=["full", "filtered"], required=True)
    prep.add_argument("--since")
    prep.add_argument("--until")
    prep.add_argument("--reason", default="")
    prep.add_argument("--session", help="Exact session ID, unique prefix, or source path")
    nxt = sub.add_parser("next")
    nxt.add_argument("--run", required=True)
    nxt.add_argument("--worker", default="default")
    nxt.add_argument("--max-chars", type=int, default=DEFAULT_PACKET_CHARS)
    rec = sub.add_parser("record")
    rec.add_argument("--run", required=True)
    rec.add_argument("--batch", required=True)
    rec.add_argument("--input", required=True)
    sho = sub.add_parser("show")
    target = sho.add_mutually_exclusive_group(required=True)
    target.add_argument("--evidence")
    target.add_argument("--event")
    sho.add_argument("--start", type=int, default=0)
    sho.add_argument("--chars", type=int, default=DEFAULT_PACKET_CHARS)
    fin = sub.add_parser("finish")
    fin.add_argument("--run", required=True)
    sta = sub.add_parser("status")
    sta.add_argument("--run")
    sta.add_argument("--source", help="Physical source path for per-source progress")
    findings = sub.add_parser("incidents")
    findings.add_argument("--run", required=True)
    findings.add_argument("--after", default="")
    findings.add_argument("--limit", type=int, default=50)
    feedback = sub.add_parser("feedback")
    feedback.add_argument("--import", dest="refresh", action="store_true")
    feedback.add_argument("--after", default="")
    feedback.add_argument("--limit", type=int, default=50)
    feedback.add_argument("--ack", metavar="ALERT_ID", help="Mark one rated alert reviewed after synthesis")
    reg = sub.add_parser("register-session")
    reg.add_argument("--session-id", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--event", required=True)
    cap.add_argument("--quote", required=True)
    cap.add_argument("--category", required=True)
    cap.add_argument("--severity", required=True)
    cap.add_argument("--explanation", required=True)
    cap.add_argument("--pattern-id")
    cap.add_argument("--user-summary")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = _config(args.config)
        repo, _ = _paths(config)
        if args.command == "prepare":
            output = prepare(config, mode=args.mode, since=args.since, until=args.until,
                             reason=args.reason, session=args.session)
        elif args.command == "register-session":
            output = register_session(repo, args.session_id)
        elif args.command == "feedback" and args.refresh:
            output = import_feedback(config)
        else:
            conn = _connect(repo)
            try:
                if args.command == "next":
                    output = next_batch(conn, args.run, args.worker, args.max_chars)
                elif args.command == "record":
                    report = json.loads(Path(args.input).read_text(encoding="utf-8"))
                    output = record(conn, args.run, args.batch, report)
                elif args.command == "show":
                    output = (show(conn, args.evidence, start=args.start, chars=args.chars)
                              if args.evidence else show_event(conn, args.event, start=args.start, chars=args.chars))
                elif args.command == "finish":
                    output = finish(conn, repo, args.run)
                elif args.command == "capture":
                    output = capture(conn, repo, args.event, quote=args.quote,
                                     category=args.category, severity=args.severity,
                                     explanation=args.explanation, pattern_id=args.pattern_id,
                                     user_summary=args.user_summary)
                elif args.command == "incidents":
                    output = list_incidents(conn, args.run, after=args.after, limit=args.limit)
                elif args.command == "feedback":
                    output = (acknowledge_feedback(conn, args.ack) if args.ack
                              else feedback_summary(conn, after=args.after, limit=args.limit))
                else:
                    if args.source and not args.run:
                        raise AuditError("--source requires --run")
                    output = (source_progress(conn, args.run, args.source) if args.source
                              else progress(conn, args.run) if args.run else latest_progress(conn))
            finally:
                conn.close()
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (AuditError, OSError, ValueError, KeyError, sqlite3.DatabaseError) as exc:
        print(f"slop-audit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
