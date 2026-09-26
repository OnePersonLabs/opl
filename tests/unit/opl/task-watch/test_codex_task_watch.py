#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = REPOSITORY_ROOT / "plugins" / "opl" / "scripts" / "codex-task-watch.py"
SPEC = importlib.util.spec_from_file_location("codex_task_watch", MODULE_PATH)
assert SPEC and SPEC.loader
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)

SESSION_ONE = "11111111-1111-4111-8111-111111111111"
SESSION_TWO = "22222222-2222-4222-8222-222222222222"


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class TaskWatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state" / "watch.sqlite3"
        self.rollout = self.root / "rollout.jsonl"
        self.rollout.write_text("start\n", encoding="utf-8")
        self.connection = watch.connect_db(self.state)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp.cleanup()

    def event(
        self,
        name: str,
        *,
        session_id: str = SESSION_ONE,
        now: float = 100.0,
        connection=None,
        **extra,
    ):
        payload = {
            "hook_event_name": name,
            "session_id": session_id,
            "cwd": str(self.root / "example-project"),
            "transcript_path": str(self.rollout),
            **extra,
        }
        watch.record_hook_event(connection or self.connection, payload, now=now)

    def row(self, session_id: str = SESSION_ONE):
        return self.connection.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()

    def test_lifecycle_events_activate_reset_and_stop_without_losing_last_response(self) -> None:
        for index, name in enumerate(sorted(watch.ACTIVE_EVENTS), start=1):
            self.event(name, now=float(index))
            row = self.row()
            self.assertEqual(row["state"], "active")
            self.assertEqual(row["last_activity"], float(index))
            self.assertEqual(row["alert_sent"], 0)

        self.event("Stop", now=50, last_assistant_message="finished earlier")
        row = self.row()
        self.assertEqual(row["state"], "inactive")
        self.assertEqual(row["last_assistant_message"], "finished earlier")
        self.assertEqual(row["last_activity"], float(len(watch.ACTIVE_EVENTS)))

        self.event("PostToolUse", now=60)
        self.assertEqual(self.row()["state"], "active")
        self.assertEqual(self.row()["last_activity"], 60)
        for event in ("Interrupt", "SessionEnd"):
            self.event(event, now=70)
            self.assertEqual(self.row()["state"], "inactive")

    def test_subagent_activity_updates_parent_session_and_concurrent_sessions(self) -> None:
        self.event("SubagentStart", now=10)
        self.event("UserPromptSubmit", session_id=SESSION_TWO, now=20)
        self.event("SubagentStop", now=30)
        self.assertEqual(self.row()["last_activity"], 30)
        self.assertEqual(self.row(SESSION_TWO)["last_activity"], 20)

    def test_rollout_growth_rearms_only_active_sessions(self) -> None:
        self.event("UserPromptSubmit", now=10)
        self.connection.execute(
            "UPDATE sessions SET alert_sent=1 WHERE session_id=?", (SESSION_ONE,)
        )
        self.connection.commit()
        self.rollout.write_text("start\nmore\n", encoding="utf-8")
        self.assertEqual(watch.refresh_rollout_activity(self.connection, now=20), 1)
        row = self.row()
        self.assertEqual(row["last_activity"], 20)
        self.assertEqual(row["alert_sent"], 0)

        self.event("Stop", now=21)
        self.rollout.write_text("start\nmore\nfinal\n", encoding="utf-8")
        self.assertEqual(watch.refresh_rollout_activity(self.connection, now=30), 0)
        self.assertEqual(self.row()["state"], "inactive")

    def test_one_alert_per_silence_episode_and_failure_is_retained_for_retry(self) -> None:
        self.event("UserPromptSubmit", now=10)
        sent = []

        def sender(url, token, title, message):
            sent.append((url, token, title, message))

        result = watch.deliver_due_notifications(
            self.connection,
            idle=25,
            url="https://ntfy.example/topic",
            token="secret",
            now=40,
            sender=sender,
        )
        self.assertEqual(result, (1, 0))
        self.assertEqual(len(sent), 1)
        self.assertIn("Project: example-project", sent[0][3])
        watch.deliver_due_notifications(
            self.connection, idle=25, url="https://ntfy.example/topic", token=None, now=80, sender=sender
        )
        self.assertEqual(len(sent), 1)

        self.event("PostToolUse", now=90)

        def failing(*_args):
            raise watch.WatchError("token=must-not-appear")

        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            result = watch.deliver_due_notifications(
                self.connection,
                idle=25,
                url="https://ntfy.example/topic",
                token=None,
                now=120,
                sender=failing,
            )
        self.assertEqual(result, (0, 1))
        self.assertEqual(self.row()["alert_sent"], 0)
        self.assertEqual(self.row()["next_notify_at"], 120 + watch.DEFAULT_RETRY_SECONDS)
        self.assertIn("error=WatchError", stderr.getvalue())
        self.assertNotIn("must-not-appear", stderr.getvalue())

    def test_activity_during_delivery_is_not_marked_as_already_alerted(self) -> None:
        self.event("UserPromptSubmit", now=10)

        def sender(*_args):
            self.event("PostToolUse", now=50)

        result = watch.deliver_due_notifications(
            self.connection,
            idle=25,
            url="https://ntfy.example/topic",
            token=None,
            now=40,
            sender=sender,
        )
        self.assertEqual(result, (1, 0))
        row = self.row()
        self.assertEqual(row["last_activity"], 50)
        self.assertEqual(row["alert_sent"], 0)
        self.assertIsNone(row["next_notify_at"])
        self.assertEqual(len(watch.due_sessions(self.connection, 25, 80)), 1)

    def test_notification_commits_before_the_next_sender_can_record_activity(self) -> None:
        self.event("UserPromptSubmit", now=10)
        self.event("UserPromptSubmit", session_id=SESSION_TWO, now=10)
        calls = 0

        def sender(*_args):
            nonlocal calls
            calls += 1
            if calls == 2:
                observer = watch.connect_db(self.state)
                try:
                    self.event("PostToolUse", now=50, connection=observer)
                finally:
                    observer.close()

        result = watch.deliver_due_notifications(
            self.connection,
            idle=25,
            url="https://ntfy.example/topic",
            token=None,
            now=40,
            sender=sender,
        )
        self.assertEqual(result, (2, 0))
        self.assertEqual(self.row()["last_activity"], 50)
        self.assertEqual(self.row()["alert_sent"], 0)

    def test_inactive_sessions_never_alert(self) -> None:
        self.event("UserPromptSubmit", now=10)
        self.event("Stop", now=11)
        sent = []
        result = watch.deliver_due_notifications(
            self.connection,
            idle=25,
            url="https://ntfy.example/topic",
            token=None,
            now=100,
            sender=lambda *_args: sent.append(True),
        )
        self.assertEqual(result, (0, 0))
        self.assertEqual(sent, [])

    def test_metadata_precedence_and_fallback(self) -> None:
        self.event("UserPromptSubmit", now=10)

        class Resolver:
            def __init__(self, _cwd):
                pass

            def read(self, _session_id):
                return "Named task", "Preview task"

            def close(self):
                pass

        rows = watch.fetch_sessions(self.connection)
        watch.resolve_missing_metadata(self.connection, rows, resolver_factory=Resolver, now=20)
        self.assertEqual(watch.session_name(self.row()), "Named task")
        self.connection.execute(
            "UPDATE sessions SET display_name=NULL, preview='Preview task' WHERE session_id=?", (SESSION_ONE,)
        )
        self.connection.commit()
        self.assertEqual(watch.session_name(self.row()), "Preview task")
        self.connection.execute(
            "UPDATE sessions SET preview=NULL WHERE session_id=?", (SESSION_ONE,)
        )
        self.connection.commit()
        self.assertEqual(watch.session_name(self.row()), f"example-project ({SESSION_ONE[:8]})")

    def test_metadata_commits_before_the_next_resolver_read(self) -> None:
        self.event("UserPromptSubmit", now=10)
        self.event("UserPromptSubmit", session_id=SESSION_TWO, now=10)

        class Resolver:
            calls = 0

            def __init__(self, _cwd):
                pass

            def read(self, session_id):
                self.calls += 1
                if self.calls == 2:
                    observer = watch.connect_db(self_state)
                    try:
                        watch.record_hook_event(
                            observer,
                            {
                                "hook_event_name": "PostToolUse",
                                "session_id": SESSION_ONE,
                                "cwd": str(root),
                                "transcript_path": str(rollout),
                            },
                            now=50,
                        )
                    finally:
                        observer.close()
                return f"task {session_id[:8]}", None

            def close(self):
                pass

        self_state = self.state
        root = self.root
        rollout = self.rollout
        watch.resolve_missing_metadata(
            self.connection, watch.fetch_sessions(self.connection), resolver_factory=Resolver, now=20
        )
        self.assertEqual(self.row(SESSION_TWO)["display_name"], f"task {SESSION_TWO[:8]}")
        self.assertEqual(self.row()["last_activity"], 50)

    def test_ntfy_payload_auth_retry_and_utf8_truncation(self) -> None:
        requests = []
        sleeps = []

        def opener(request, timeout):
            requests.append((request, timeout))
            if len(requests) == 1:
                raise urllib.error.URLError("temporary")
            return Response()

        watch.send_ntfy(
            "https://ntfy.example/base/topic",
            "private-token",
            "title",
            "🙂" * 2000,
            opener=opener,
            sleep=sleeps.append,
        )
        self.assertEqual(len(requests), 2)
        request = requests[-1][0]
        self.assertEqual(request.full_url, "https://ntfy.example/base/")
        self.assertEqual(request.headers["Authorization"], "Bearer private-token")
        payload = json.loads(request.data)
        self.assertEqual(payload["topic"], "topic")
        self.assertLessEqual(len(payload["message"].encode("utf-8")), watch.MAX_NTFY_MESSAGE_BYTES)
        self.assertEqual(len(sleeps), 1)

    def test_hook_malformed_input_never_blocks(self) -> None:
        stderr = io.StringIO()
        with patch("sys.stdin", io.StringIO("not json")), patch("sys.stderr", stderr):
            code = watch.main(["--state", str(self.state), "hook"])
        self.assertEqual(code, 0)
        self.assertIn("hook ignored", stderr.getvalue())

    def test_restart_recovery_status_json_and_prune(self) -> None:
        self.event("UserPromptSubmit", now=10)
        self.connection.close()
        self.connection = watch.connect_db(self.state)
        self.assertEqual(self.row()["state"], "active")
        self.connection.execute("UPDATE sessions SET updated_at=1")
        self.connection.commit()
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = watch.main(["--state", str(self.state), "prune", "--older-than", "1d"])
        self.assertEqual(code, 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_duration_and_ntfy_target_validation(self) -> None:
        self.assertEqual(watch.parse_duration("25m"), 1500)
        for value in ("nanm", "infh", "-infs", "1e308d"):
            with self.assertRaises(argparse.ArgumentTypeError):
                watch.parse_duration(value)
        self.assertEqual(watch.ntfy_target("https://ntfy.sh/topic"), ("https://ntfy.sh/", "topic"))
        with self.assertRaises(watch.WatchError):
            watch.ntfy_target("http://ntfy.sh/topic")

    def test_launcher_resolves_the_shipped_script_outside_the_checkout(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        environment = {**os.environ, "CODEX_HOME": str(self.root / "codex-home")}
        result = subprocess.run(
            [
                "node",
                str(REPOSITORY_ROOT / "tools" / "codex-watch.mjs"),
                "--state",
                str(self.state),
                "status",
                "--json",
            ],
            cwd=outside,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_manifest_observes_every_lifecycle_event_in_order(self) -> None:
        manifest = json.loads(
            (REPOSITORY_ROOT / "plugins" / "opl" / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )["hooks"]
        expected = watch.ACTIVE_EVENTS | watch.INACTIVE_EVENTS
        for event in expected:
            handlers = [
                handler
                for group in manifest[event]
                for handler in group["hooks"]
                if "codex-task-watch.py" in handler.get("command", "")
            ]
            self.assertEqual(len(handlers), 1, event)
            self.assertNotIn("async", handlers[0], event)
            self.assertEqual(handlers[0]["timeout"], 3, event)


if __name__ == "__main__":
    unittest.main()
