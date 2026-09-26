#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = REPOSITORY_ROOT / "plugins" / "opl" / "skills" / "session-reader" / "scripts" / "session_reader.py"
SPEC = importlib.util.spec_from_file_location("session_reader", MODULE_PATH)
assert SPEC and SPEC.loader
reader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reader
SPEC.loader.exec_module(reader)


ID_ONE = "11111111-1111-4111-8111-111111111111"
ID_TWO = "11111111-1111-4111-8111-222222222222"


def record(timestamp: str, record_type: str, payload: dict) -> dict:
    return {"timestamp": timestamp, "type": record_type, "payload": payload}


def meta(session_id: str, timestamp: str, cwd: str = "/work/example") -> dict:
    return record(timestamp, "session_meta", {"id": session_id, "timestamp": timestamp, "cwd": cwd})


def user(timestamp: str, text: str) -> dict:
    return record(timestamp, "event_msg", {"type": "user_message", "message": text})


def agent(timestamp: str, text: str, phase: str | None = "final_answer") -> dict:
    payload = {"type": "agent_message", "message": text}
    if phase is not None:
        payload["phase"] = phase
    return record(timestamp, "event_msg", payload)


def response(timestamp: str, role: str, text: str, phase: str | None = None) -> dict:
    payload = {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}
    if phase:
        payload["phase"] = phase
    return record(timestamp, "response_item", payload)


class SessionReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex_home = self.root / "codex"
        self.cache = self.root / "cache" / "index.sqlite3"
        (self.codex_home / "sessions" / "2026" / "07" / "20").mkdir(parents=True)
        self.conn = reader.connect_db(self.cache)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp.cleanup()

    def path_for(self, session_id: str = ID_ONE, *, archived: bool = False) -> Path:
        root = (
            self.codex_home / "archived_sessions"
            if archived
            else self.codex_home / "sessions" / "2026" / "07" / "20"
        )
        root.mkdir(parents=True, exist_ok=True)
        return root / f"rollout-2026-07-20T00-00-00-{session_id}.jsonl"

    def write_records(self, path: Path, records: list[dict], *, trailing_newline: bool = True) -> None:
        body = "\n".join(json.dumps(item, ensure_ascii=False) for item in records)
        if trailing_newline:
            body += "\n"
        path.write_text(body, encoding="utf-8")

    def refresh(self) -> dict[str, int]:
        return reader.refresh_index(self.conn, self.codex_home)

    def test_canonical_events_beat_injected_response_items(self) -> None:
        path = self.path_for()
        self.write_records(
            path,
            [
                meta(ID_ONE, "2026-07-20T00:00:00Z"),
                response("2026-07-20T00:00:01Z", "user", "# AGENTS injected context"),
                user("2026-07-20T00:00:02Z", "actual user request"),
                response("2026-07-20T00:00:03Z", "assistant", "duplicate commentary", "commentary"),
                agent("2026-07-20T00:00:03Z", "working", "commentary"),
                agent("2026-07-20T00:00:04Z", "finished", "final_answer"),
            ],
        )
        stats = self.refresh()
        self.assertEqual(stats["reindexed"], 1)
        session = self.conn.execute("SELECT * FROM sessions").fetchone()
        self.assertEqual(session["schema_kind"], "event_msg")
        self.assertEqual(session["message_count"], 3)
        rows = self.conn.execute("SELECT * FROM messages ORDER BY message_no").fetchall()
        self.assertEqual([row["text"] for row in rows], ["actual user request", "working", "finished"])
        self.assertEqual([row["message_no"] for row in rows], [1, 2, 3])
        self.assertEqual([row["raw_line"] for row in rows], [3, 5, 6])
        self.assertGreater(rows[1]["byte_offset"], rows[0]["byte_offset"])

    def test_phase_less_legacy_agent_message_is_final(self) -> None:
        path = self.path_for()
        self.write_records(
            path,
            [meta(ID_ONE, "2026-02-06T00:00:00Z"), user("2026-02-06T00:00:01Z", "old ask"), agent("2026-02-06T00:00:02Z", "old answer", None)],
        )
        self.refresh()
        row = self.conn.execute("SELECT * FROM messages WHERE role='assistant'").fetchone()
        self.assertEqual(row["phase"], "final_answer")

    def test_session_meta_identity_overrides_filename_identity(self) -> None:
        path = self.path_for(ID_TWO)
        self.write_records(
            path,
            [
                meta(ID_ONE, "2026-07-20T00:00:00Z"),
                meta(ID_TWO, "2026-07-19T00:00:00Z"),
                user("2026-07-20T00:00:01Z", "renamed rollout"),
            ],
        )
        self.refresh()
        session = self.conn.execute("SELECT session_id, path FROM sessions").fetchone()
        self.assertEqual(session["session_id"], ID_ONE)
        self.assertEqual(session["path"], str(path.resolve()))

    def test_response_items_are_labeled_fallback_when_events_absent(self) -> None:
        path = self.path_for()
        self.write_records(
            path,
            [
                meta(ID_ONE, "2026-01-01T00:00:00Z"),
                response("2026-01-01T00:00:01Z", "user", "fallback ask"),
                response("2026-01-01T00:00:02Z", "assistant", "fallback answer"),
            ],
        )
        self.refresh()
        session = self.conn.execute("SELECT * FROM sessions").fetchone()
        self.assertEqual(session["schema_kind"], "response_item_fallback")
        sources = self.conn.execute("SELECT DISTINCT source FROM messages").fetchall()
        self.assertEqual([row[0] for row in sources], ["response_item_fallback"])

    def test_malformed_line_reported_and_partial_tail_resumed(self) -> None:
        path = self.path_for()
        valid = [meta(ID_ONE, "2026-07-20T00:00:00Z"), user("2026-07-20T00:00:01Z", "first")]
        path.write_bytes(
            ("\n".join(json.dumps(item) for item in valid) + "\n{bad json}\n").encode()
            + b'{"timestamp":'
        )
        self.refresh()
        before = self.conn.execute("SELECT * FROM sessions").fetchone()
        self.assertEqual(before["malformed_count"], 1)
        self.assertLess(before["indexed_offset"], path.stat().st_size)

        with path.open("ab") as handle:
            handle.write(
                b'"2026-07-20T00:00:02Z","type":"event_msg","payload":{"type":"agent_message","message":"done","phase":"final_answer"}}\n'
            )
        stats = self.refresh()
        self.assertEqual(stats["appended"], 1)
        after = self.conn.execute("SELECT * FROM sessions").fetchone()
        self.assertEqual(after["message_count"], 2)
        self.assertEqual(after["malformed_count"], 1)
        self.assertEqual(after["indexed_offset"], path.stat().st_size)

    def test_append_move_archive_and_prune(self) -> None:
        path = self.path_for()
        self.write_records(
            path,
            [meta(ID_ONE, "2026-07-20T00:00:00Z"), user("2026-07-20T00:00:01Z", "one")],
        )
        self.refresh()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(agent("2026-07-20T00:00:02Z", "two")) + "\n")
        stats = self.refresh()
        self.assertEqual(stats["appended"], 1)
        self.assertEqual(self.conn.execute("SELECT message_count FROM sessions").fetchone()[0], 2)

        archived = self.path_for(archived=True)
        path.replace(archived)
        stats = self.refresh()
        self.assertEqual(stats["unchanged"], 1)
        row = self.conn.execute("SELECT path, archived FROM sessions").fetchone()
        self.assertEqual(row["path"], str(archived.resolve()))
        self.assertEqual(row["archived"], 1)

        archived.unlink()
        stats = self.refresh()
        self.assertEqual(stats["pruned"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_rewrite_reindexes_instead_of_appending(self) -> None:
        path = self.path_for()
        self.write_records(
            path,
            [meta(ID_ONE, "2026-07-20T00:00:00Z"), user("2026-07-20T00:00:01Z", "original")],
        )
        self.refresh()
        self.write_records(
            path,
            [meta(ID_ONE, "2026-07-21T00:00:00Z"), user("2026-07-21T00:00:01Z", "replacement text")],
        )
        stats = self.refresh()
        self.assertEqual(stats["reindexed"], 1)
        self.assertEqual(self.conn.execute("SELECT text FROM messages").fetchone()[0], "replacement text")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'original'").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'replacement'").fetchone()[0],
            1,
        )

    def test_conversation_view_preserves_global_message_numbers(self) -> None:
        path = self.path_for()
        self.write_records(
            path,
            [
                meta(ID_ONE, "2026-07-20T00:00:00Z"),
                user("2026-07-20T00:00:01Z", "ask"),
                agent("2026-07-20T00:00:02Z", "progress", "commentary"),
                agent("2026-07-20T00:00:03Z", "answer"),
            ],
        )
        self.refresh()
        args = Namespace(range=None, view="conversation", roles=None, phases=None)
        rows = reader.fetch_show_rows(self.conn, args, ID_ONE)
        self.assertEqual([row["message_no"] for row in rows], [1, 3])
        args.range = "2:3"
        rows = reader.fetch_show_rows(self.conn, args, ID_ONE)
        self.assertEqual([row["message_no"] for row in rows], [3])

    def test_show_cap_stops_on_message_boundary_with_cursor(self) -> None:
        path = self.path_for()
        self.write_records(
            path,
            [
                meta(ID_ONE, "2026-07-20T00:00:00Z"),
                user("2026-07-20T00:00:01Z", "a" * 700),
                agent("2026-07-20T00:00:02Z", "b" * 700),
            ],
        )
        self.refresh()
        rows = self.conn.execute(
            "SELECT m.*, s.path FROM messages m JOIN sessions s USING(session_id) ORDER BY message_no"
        ).fetchall()
        args = Namespace(message_chars=1000, max_output_chars=1000)
        messages, truncated, next_start = reader.bounded_messages(rows, args)
        self.assertEqual(len(messages), 1)
        self.assertTrue(truncated)
        self.assertEqual(next_start, 2)

    def test_search_modes_filters_order_and_context(self) -> None:
        first = self.path_for(ID_ONE)
        second = self.path_for(ID_TWO)
        self.write_records(
            first,
            [meta(ID_ONE, "2026-07-19T00:00:00Z", "/work/one"), user("2026-07-19T00:00:01Z", "alpha needle")],
        )
        self.write_records(
            second,
            [
                meta(ID_TWO, "2026-07-20T00:00:00Z", "/work/two"),
                user("2026-07-20T00:00:01Z", "before"),
                agent("2026-07-20T00:00:02Z", "Needle beta"),
            ],
        )
        self.refresh()

        base = dict(
            query="needle",
            session=None,
            roles=None,
            phases=None,
            since=None,
            until=None,
            archive="both",
            cwd=None,
            order="newest",
            limit=20,
            offset=0,
            ignore_case=True,
        )
        rows = reader.search_rows(self.conn, Namespace(mode="fts", **base))
        self.assertEqual([row["session_id"] for row in rows], [ID_TWO, ID_ONE])
        rows = reader.search_rows(self.conn, Namespace(mode="literal", **base))
        self.assertEqual(len(rows), 2)
        regex = {**base, "query": r"Needle\s+beta"}
        rows = reader.search_rows(self.conn, Namespace(mode="regex", **regex))
        self.assertEqual([row["session_id"] for row in rows], [ID_TWO])
        context = reader.context_for(self.conn, rows[0], 1)
        self.assertEqual([item["message_no"] for item in context], [1])

        command_args = Namespace(
            mode="literal",
            format="json",
            excerpt_chars=120,
            max_output_chars=1000,
            context=0,
            **{**base, "limit": 1},
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            reader.command_search(self.conn, command_args)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_offset"], 1)
        self.assertEqual(payload["results"][0]["session_id"], ID_TWO)

    def test_date_only_bounds_are_inclusive_and_search_output_is_bounded(self) -> None:
        args = Namespace(
            limit=20,
            excerpt_chars=240,
            message_chars=4000,
            max_output_chars=1000,
            context=0,
            offset=0,
            since="2026-07-20",
            until="2026-07-20",
        )
        reader.validate_bounds(args)
        self.assertEqual(args.since, "2026-07-20T00:00:00Z")
        self.assertEqual(args.until, "2026-07-20T23:59:59.999999Z")

    def test_unique_prefix_and_ambiguous_prefix(self) -> None:
        for session_id in (ID_ONE, ID_TWO):
            path = self.path_for(session_id)
            self.write_records(path, [meta(session_id, "2026-07-20T00:00:00Z"), user("2026-07-20T00:00:01Z", session_id)])
        self.refresh()
        self.assertEqual(reader.resolve_session(self.conn, ID_ONE)["session_id"], ID_ONE)
        with self.assertRaises(reader.ReaderError):
            reader.resolve_session(self.conn, "11111111")

    def test_json_cli_and_cache_permissions(self) -> None:
        path = self.path_for()
        self.write_records(path, [meta(ID_ONE, "2026-07-20T00:00:00Z"), user("2026-07-20T00:00:01Z", "hello")])
        self.conn.close()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = reader.main(
                [
                    "--codex-home",
                    str(self.codex_home),
                    "--cache",
                    str(self.cache),
                    "sessions",
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload[0]["session_id"], ID_ONE)
        if sys.platform != "win32":
            # Windows access is governed by inherited ACLs, not POSIX mode bits.
            mode = stat.S_IMODE(self.cache.stat().st_mode)
            self.assertEqual(mode & 0o077, 0)
        self.conn = reader.connect_db(self.cache)


if __name__ == "__main__":
    unittest.main()
