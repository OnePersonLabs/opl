"""Daily launcher checks use isolated repositories and no real model process."""

import os
import io
import json
import importlib.util
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[4] / "plugins" / "opl" / "skills" / "slop-buster" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import slop_daily


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "data repo"
        (self.repo / ".git").mkdir(parents=True)
        self.config = {"data_repo": str(self.repo), "deadline_seconds": 1800,
                       "models": {"orchestrator": {"name": "gpt-6-sol", "effort": "medium"}}}
        self.path = Path(self.temp.name) / "config.toml"

    def test_no_new_work_never_starts_model_and_finishes_run(self):
        progress = {"run_id": "r1", "total": 0, "pending": 0, "completed": 0, "status": "prepared"}
        complete = {**progress, "status": "complete"}
        def audit(_path, _repo, command, *_args, **_kwargs):
            return {"run_id": "r1", "progress": progress,
                    "feedback_counts": {"pending_review": 0}} if command == "prepare" else complete
        with patch.object(slop_daily, "load_config", return_value=self.config), \
             patch.object(slop_daily, "config_file", return_value=self.path), \
             patch.object(slop_daily, "_audit_json", side_effect=audit) as called, \
             patch.object(slop_daily.subprocess, "Popen") as model:
            result = slop_daily.run_daily()
        self.assertEqual(result["status"], "no_new_work")
        self.assertEqual([call.args[2] for call in called.call_args_list], ["prepare", "finish", "status"])
        model.assert_not_called()
        self.assertEqual(len(list((self.repo / ".runtime" / "daily-runs").glob("*.json"))), 1)
        self.assertFalse((self.repo / ".runtime" / "daily.lock").exists())

    def test_feedback_pending_review_starts_one_orchestration_without_new_chunks(self):
        prepared = {"run_id": "r-feedback", "progress": {"pending": 0, "claimed": 0, "status": "prepared"},
                    "feedback_counts": {"pending_review": 1}}
        status = {"run_id": "r-feedback", "pending": 0, "claimed": 0, "status": "complete"}
        process = MagicMock()
        process.stdin = MagicMock()
        process.stdout = io.StringIO("")
        process.wait.return_value = 0
        with patch.object(slop_daily, "load_config", return_value=self.config), \
             patch.object(slop_daily, "config_file", return_value=self.path), \
             patch.object(slop_daily, "_audit_json", side_effect=[prepared, status,
                                                         {"counts": {"pending_review": 0}}]) as audit, \
             patch.object(slop_daily.subprocess, "Popen", return_value=process) as model:
            result = slop_daily.run_daily(codex="codex-test")
        model.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["feedback_pending_review"], 0)
        self.assertEqual([call.args[2] for call in audit.call_args_list], ["prepare", "status", "feedback"])
        self.assertIn("acknowledge each alert", process.stdin.write.call_args.args[0])

    def test_filtered_without_discovery_requests_initial_full(self):
        prepared = {"run_id": "r0", "discovery_required": True,
                    "progress": {"total": 0, "pending": 0, "needs_full_discovery": True}}
        with patch.object(slop_daily, "load_config", return_value=self.config), \
             patch.object(slop_daily, "config_file", return_value=self.path), \
             patch.object(slop_daily, "_audit_json", return_value=prepared), \
             patch.object(slop_daily.subprocess, "Popen") as model:
            result = slop_daily.run_daily()
        self.assertEqual(result["status"], "needs_initial_full")
        model.assert_not_called()

    def test_source_gaps_are_reported_without_false_no_work(self):
        prepared = {"run_id": "r-gap", "progress": {"pending": 0, "claimed": 0,
                    "source_gaps": [{"kind": "partial_tail", "sources": 1, "amount": 9}]}}
        with patch.object(slop_daily, "load_config", return_value=self.config), \
             patch.object(slop_daily, "config_file", return_value=self.path), \
             patch.object(slop_daily, "_audit_json", return_value=prepared) as audit, \
             patch.object(slop_daily.subprocess, "Popen") as model:
            result = slop_daily.run_daily(mode="full")
        self.assertEqual(result["status"], "source_gaps")
        self.assertEqual(result["coverage"]["source_gaps"][0]["kind"], "partial_tail")
        self.assertEqual(audit.call_count, 1)
        model.assert_not_called()

    def test_scheduled_filtered_resumes_full_discovery(self):
        filtered = {"run_id": "filtered", "discovery_required": True,
                    "progress": {"pending": 0, "needs_full_discovery": True}}
        full = {"run_id": "full", "progress": {"pending": 0, "needs_full_discovery": True}}
        done = {"run_id": "full", "status": "complete", "pending": 0, "total": 0}
        with patch.object(slop_daily, "load_config", return_value=self.config), \
             patch.object(slop_daily, "config_file", return_value=self.path), \
             patch.object(slop_daily, "_audit_json", side_effect=[filtered, full, done, done]) as audit, \
             patch.object(slop_daily.subprocess, "Popen") as model:
            result = slop_daily.run_daily(scheduled=True)
        self.assertEqual(result["mode"], "full")
        self.assertEqual(result["status"], "no_new_work")
        self.assertEqual([call.args[2] for call in audit.call_args_list], ["prepare", "prepare", "finish", "status"])
        model.assert_not_called()

    def test_json_events_register_session_and_report_usage(self):
        prepared = {"run_id": "r3", "progress": {"total": 1, "pending": 1}}
        status = {"run_id": "r3", "status": "complete", "total": 1, "pending": 0, "completed": 1}
        process = MagicMock()
        process.stdin = MagicMock()
        process.stdout = io.StringIO('\n'.join([
            json.dumps({"type": "thread.started", "thread_id": "session-123"}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 2}}),
        ]) + '\n')
        process.wait.return_value = 0
        with patch.object(slop_daily, "load_config", return_value=self.config), \
             patch.object(slop_daily, "config_file", return_value=self.path), \
             patch.object(slop_daily, "_audit_json", side_effect=[prepared, {"session_id": "session-123"}, status,
                                                          {"counts": {"pending_review": 0}}]) as audit, \
             patch.object(slop_daily.subprocess, "Popen", return_value=process):
            result = slop_daily.run_daily(codex="codex-test")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage"], {"input_tokens": 4, "output_tokens": 2})
        self.assertTrue(result["usage_available"])
        self.assertEqual(audit.call_args_list[1].args[2:], ("register-session", "--session-id", "session-123"))
        self.assertTrue(Path(result["codex_event_log"]).exists())

    def test_claimed_audit_packet_is_not_mistaken_for_no_work(self):
        spec = importlib.util.spec_from_file_location("slop_audit_daily_test", SCRIPTS / "slop_audit.py")
        audit = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = audit
        spec.loader.exec_module(audit)
        home = Path(self.temp.name) / "source"
        sessions = home / "sessions" / "2026" / "09" / "27"
        sessions.mkdir(parents=True)
        session_id = "11111111-1111-4111-8111-111111111111"
        path = sessions / f"rollout-{session_id}.jsonl"
        def event(at, kind, payload):
            return {"timestamp": at, "type": kind, "payload": payload}
        records = [
            event("2026-09-27T00:00:00Z", "session_meta", {"id": session_id}),
            event("2026-09-27T00:00:01Z", "event_msg", {"type": "user_message", "message": "Ask"}),
            event("2026-09-27T00:00:02Z", "event_msg", {"type": "agent_message", "message": "Wrong answer", "phase": "final_answer"}),
        ]
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        self.path.write_text(f'data_repo = {json.dumps(str(self.repo))}\nsource_homes = [{json.dumps(str(home))}]\n', encoding="utf-8")
        config = slop_daily.load_config(str(self.path))
        prepared = audit.prepare(config, mode="full")
        connection = audit._connect(self.repo)
        try:
            packet = audit.next_batch(connection, prepared["run_id"], "default")
            self.assertTrue(packet["batch_id"])
            self.assertEqual(audit.progress(connection, prepared["run_id"])["pending"], 0)
            self.assertGreater(audit.progress(connection, prepared["run_id"])["claimed"], 0)
        finally:
            connection.close()
        process = MagicMock()
        process.stdin = MagicMock()
        process.stdout = io.StringIO("")
        process.wait.return_value = 0
        original_popen = subprocess.Popen
        def launch(command, **kwargs):
            return process if command[0] == "codex-test" else original_popen(command, **kwargs)
        with patch.object(slop_daily.subprocess, "Popen", side_effect=launch) as model:
            result = slop_daily.run_daily(str(self.path), mode="full", codex="codex-test")
        self.assertEqual(sum(call.args[0][0] == "codex-test" for call in model.call_args_list), 1)
        self.assertEqual(result["status"], "incomplete")
        self.assertGreater(result["coverage"]["claimed"], 0)

    def test_one_explicit_model_process_and_incomplete_result(self):
        prepared = {"run_id": "r2", "progress": {"total": 2, "pending": 2}}
        status = {"run_id": "r2", "status": "prepared", "total": 2, "pending": 1, "completed": 1}
        process = MagicMock()
        process.stdin = MagicMock()
        process.wait.return_value = 0
        with patch.object(slop_daily, "load_config", return_value=self.config), \
             patch.object(slop_daily, "config_file", return_value=self.path), \
             patch.object(slop_daily, "_audit_json", side_effect=[prepared, status,
                                                          {"counts": {"pending_review": 0}}]), \
             patch.object(slop_daily.subprocess, "Popen", return_value=process) as model:
            result = slop_daily.run_daily(codex="codex-test")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(model.call_args.args[0][:6],
                         ["codex-test", "exec", "-m", "gpt-6-sol", "-c", "model_reasoning_effort=medium"])
        self.assertEqual(model.call_args.kwargs["cwd"], self.repo)
        self.assertIn("Do not invoke setup, daily", process.stdin.write.call_args.args[0])
        self.assertIn("seconds", process.stdin.write.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
