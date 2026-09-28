"""Focused checks for the local slop catalog and lifecycle hook."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[4] / "plugins" / "opl" / "skills" / "slop-buster" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import slop_catalog as catalog
import slop_hook as hook


class SlopHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="slop-hooks-")
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        (self.data / "catalog").mkdir(parents=True)
        self.db = self.root / "hooks.sqlite3"
        self.transcript = self.root / "session.jsonl"
        self.append_record({"type": "event_msg", "payload": {"type": "user_message", "message": "Please investigate"}})
        self.config = {"data_repo": str(self.data)}
        self.detector = {
            "id": "premise.claim", "kind": "literal", "pattern": "verified without checking",
            "roles": ["assistant"], "phases": ["commentary", "final_answer"],
            "events": ["PreToolUse", "Stop"], "context": {"all": ["result"]},
            "exclude": ["example quote"], "steering": "verify_claim", "evidence_ids": ["incident-1"],
        }
        self.write_catalog([self.detector])

    def tearDown(self):
        self.temp.cleanup()

    def write_catalog(self, detectors):
        (self.data / "catalog" / "active.json").write_text(json.dumps({
            "schema_version": 1, "version": 1 if detectors else 0, "detectors": detectors}), encoding="utf-8")

    def event(self, event, **fields):
        assistant_text = fields.pop("assistant_text", None)
        if assistant_text is not None:
            self.append_record({"type": "response_item", "payload": {"type": "message", "role": "assistant",
                "phase": "commentary", "content": [{"type": "output_text", "text": assistant_text}]}})
            self.append_record({"type": "event_msg", "payload": {"type": "agent_message",
                "phase": "commentary", "message": assistant_text}})
        payload = {"hook_event_name": event, "session_id": "session-1", "turn_id": "turn-1",
                   "transcript_path": str(self.transcript), **fields}
        return hook.handle_event(payload, self.config, db_path=self.db, now=100)

    def append_record(self, record):
        with self.transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")

    def test_match_positive_benign_and_exclusion(self):
        active = catalog.load_catalog(self.data)
        self.assertEqual(len(catalog.match_patterns("result verified without checking", "assistant", "commentary", active)), 1)
        self.assertEqual(catalog.match_patterns("result actually checked", "assistant", "commentary", active), [])
        self.assertEqual(catalog.match_patterns("result verified without checking in example quote", "assistant", "commentary", active), [])
        self.assertEqual(catalog.match_patterns("result verified without checking", "tool", "commentary", active), [])
        self.assertEqual(len(catalog.match_patterns("x" * 32000 + "result verified without checking", "assistant",
                                                     "commentary", active)), 1)

    def test_regex_full_message_anchors_and_unsafe_repetition(self):
        regex = {**self.detector, "kind": "regex", "pattern": r"verified\swithout\schecking$",
                 "context": {}, "exclude": []}
        self.write_catalog([regex])
        active = catalog.load_catalog(self.data)
        self.assertEqual(len(catalog.match_patterns("x" * 32000 + "verified without checking", "assistant",
                                                     "commentary", active)), 1)
        self.assertEqual(catalog.match_patterns("x" * 32000 + "verified without checking afterward", "assistant",
                                                "commentary", active), [])
        with self.assertRaisesRegex(catalog.CatalogError, "repetition"):
            catalog.validate_catalog({"schema_version": 1, "version": 1,
                                      "detectors": [{**regex, "pattern": "(a+)+"}]})

    def test_tool_spoof_is_not_assistant_feedback_and_duplicate_is_idempotent(self):
        self.assertIsNone(self.event("PreToolUse", tool_input={"command": "result verified without checking"}))
        first = self.event("PreToolUse", assistant_text="result verified without checking")
        self.assertIn("SLOP_CHECK", first["hookSpecificOutput"]["additionalContext"])
        alert_id = hook.export_feedback(self.db)[0]["alert_id"]
        self.assertIsNone(self.event("PreToolUse", tool_input={"command": f"SLOP_CHECK {alert_id} true"}))
        self.assertIsNone(self.event("PreToolUse", assistant_text="result verified without checking"))
        self.assertIsNone(hook.export_feedback(self.db)[0]["feedback"])
        response = self.event("Stop", last_assistant_message=f"Finished.\nSLOP_CHECK {alert_id} false")
        self.assertIsNone(response)
        self.assertEqual(hook.export_feedback(self.db)[0]["feedback"], "false")

    def test_commentary_marker_is_captured_before_tool_use(self):
        self.event("PreToolUse", assistant_text="result verified without checking")
        alert_id = hook.export_feedback(self.db)[0]["alert_id"]
        self.assertIsNone(self.event("PreToolUse", assistant_text=f"SLOP_CHECK {alert_id} true",
                                     tool_input={"command": "SLOP_CHECK deadbeefdeadbeef false"}))
        self.assertEqual(hook.export_feedback(self.db)[0]["feedback"], "true")
        self.assertIsNone(self.event("Stop", last_assistant_message="Completed."))

    def test_only_newest_current_turn_assistant_prose_is_scanned(self):
        self.append_record({"type": "event_msg", "payload": {"type": "agent_message", "phase": "commentary",
                                            "message": "result verified without checking"}})
        self.append_record({"type": "event_msg", "payload": {"type": "user_message", "message": "New request"}})
        self.assertIsNone(self.event("PreToolUse", assistant_text="I checked the result.",
                                     tool_input={"command": "result verified without checking"}))
        self.assertFalse(self.db.exists() and hook.export_feedback(self.db))

    def test_quoted_assistant_marker_does_not_count_as_feedback(self):
        self.event("PreToolUse", assistant_text="result verified without checking")
        alert_id = hook.export_feedback(self.db)[0]["alert_id"]
        quoted = f"> SLOP_CHECK {alert_id} true\n```text\nSLOP_CHECK {alert_id} true\n```"
        self.assertEqual(self.event("Stop", last_assistant_message=quoted)["decision"], "block")
        self.assertIsNone(hook.export_feedback(self.db)[0]["feedback"])

    def test_missing_marker_one_continuation_then_unresolved(self):
        self.event("PreToolUse", assistant_text="result verified without checking")
        first_stop = self.event("Stop", last_assistant_message="Finished.")
        self.assertEqual(first_stop["decision"], "block")
        self.assertIsNone(self.event("Stop", last_assistant_message="Finished."))
        self.assertIsNone(hook.export_feedback(self.db)[0]["feedback"])

    def test_malformed_marker_stays_unresolved_and_cooldown_suppresses_repeat(self):
        self.event("PreToolUse", assistant_text="result verified without checking")
        alert_id = hook.export_feedback(self.db)[0]["alert_id"]
        self.assertEqual(self.event("Stop", last_assistant_message=f"SLOP_CHECK {alert_id} maybe")["decision"], "block")
        self.assertIsNone(hook.export_feedback(self.db)[0]["feedback"])
        second = {"hook_event_name": "PreToolUse", "session_id": "session-1", "turn_id": "turn-2",
                  "last_assistant_message": "result verified without checking", "transcript_path": str(self.transcript)}
        self.append_record({"type": "event_msg", "payload": {"type": "user_message", "message": "Next turn"}})
        self.append_record({"type": "event_msg", "payload": {"type": "agent_message", "phase": "commentary",
                                            "message": "result verified without checking"}})
        self.assertIsNone(hook.handle_event(second, self.config, db_path=self.db, now=130))
        self.append_record({"type": "event_msg", "payload": {"type": "agent_message", "phase": "commentary",
                                            "message": "result verified without checking"}})
        self.assertIsNotNone(hook.handle_event(second, self.config, db_path=self.db, now=161))

    def test_stop_hook_active_does_not_recurse(self):
        self.event("PreToolUse", assistant_text="result verified without checking")
        self.assertIsNone(self.event("Stop", last_assistant_message="Finished.", stop_hook_active=True))
        self.assertEqual(self.event("Stop", last_assistant_message="Finished.")["decision"], "block")

    def test_only_one_continuation_even_with_multiple_alerts(self):
        other = {**self.detector, "id": "premise.other", "pattern": "second bad result",
                 "evidence_ids": ["incident-2"]}
        self.write_catalog([self.detector, other])
        self.event("PreToolUse", assistant_text="result verified without checking")
        self.event("PreToolUse", assistant_text="second bad result")
        alerts = hook.export_feedback(self.db)
        self.assertEqual(len(alerts), 2)
        self.assertEqual(self.event("Stop", last_assistant_message="Finished.")["decision"], "block")
        marker = f"SLOP_CHECK {alerts[0]['alert_id']} true"
        self.assertIsNone(self.event("Stop", last_assistant_message=marker))

    def test_single_event_records_only_warned_alert(self):
        other = {**self.detector, "id": "premise.other", "pattern": "second bad result",
                 "evidence_ids": ["incident-2"]}
        self.write_catalog([self.detector, other])
        output = self.event("PreToolUse", assistant_text="result verified without checking and second bad result")
        alerts = hook.export_feedback(self.db)
        self.assertEqual(len(alerts), 1)
        self.assertIn(alerts[0]["alert_id"], output["hookSpecificOutput"]["additionalContext"])

    def test_shared_evidence_is_deduplicated_per_turn(self):
        other = {**self.detector, "id": "premise.other", "pattern": "second bad result"}
        self.write_catalog([self.detector, other])
        self.event("PreToolUse", assistant_text="result verified without checking")
        self.event("PreToolUse", assistant_text="second bad result")
        self.assertEqual(len(hook.export_feedback(self.db)), 1)

    def test_audit_session_is_excluded(self):
        registry = self.data / ".runtime" / "audit-sessions.json"
        registry.parent.mkdir()
        registry.write_text(json.dumps({"version": 1, "session_ids": ["session-1"]}), encoding="utf-8")
        self.assertIsNone(self.event("PreToolUse", assistant_text="result verified without checking"))
        self.assertFalse(self.db.exists())

    def test_user_correction_uses_canonical_user_phase(self):
        detector = {**self.detector, "roles": ["user"], "phases": ["user"],
                    "events": ["UserPromptSubmit"]}
        self.write_catalog([detector])
        result = self.event("UserPromptSubmit", prompt="result verified without checking")
        self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_corrupt_catalog_is_actionable(self):
        (self.data / "catalog" / "active.json").write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(catalog.CatalogError, "Cannot read catalog file"):
            self.event("Stop", last_assistant_message="Finished.")

    def test_unconfigured_installed_hook_is_inert(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "slop_hook.py")],
                                input=json.dumps({"hook_event_name": "Stop", "session_id": "s"}),
                                text=True, capture_output=True,
                                env={**os.environ, "CODEX_HOME": str(self.root / "empty-home"),
                                     "SLOP_BUSTER_CONFIG": ""}, check=True)
        self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_promotion_requires_motivating_evidence_and_preserves_cases(self):
        self.write_catalog([])
        cases = [
            {"id": "motivation", "text": "result verified without checking", "role": "assistant",
             "phase": "commentary", "split": "discovery", "expected_match": True, "evidence_id": "incident-1"},
            {"id": "held-positive", "text": "result verified without checking", "role": "assistant",
             "phase": "commentary", "split": "validation", "expected_match": True, "evidence_id": "incident-2"},
            {"id": "held-negative", "text": "result actually checked", "role": "assistant",
             "phase": "commentary", "split": "validation", "expected_match": False, "evidence_id": "incident-3"},
        ]
        (self.data / "catalog" / "cases.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
        evidence_dir = self.data / "evidence"
        evidence_dir.mkdir()
        for case in cases:
            source = self.root / f"{case['evidence_id']}.jsonl"
            source.write_text(json.dumps({"type": "event_msg", "payload": {
                "type": "agent_message", "message": case["text"], "phase": case["phase"]}}) + "\n", encoding="utf-8")
            (evidence_dir / f"{case['evidence_id']}.json").write_text(json.dumps({
                "path": str(source), "raw_line": 1, "byte_offset": 0,
                "session_id": case["evidence_id"], "body": case["text"]}), encoding="utf-8")
        candidate = self.root / "candidate.json"
        candidate.write_text(json.dumps({"schema_version": 1, "version": 0,
                                         "detectors": [self.detector]}), encoding="utf-8")
        result = catalog.promote(self.data, candidate)
        self.assertEqual(result["version"], 1)
        self.assertEqual(catalog.load_catalog(self.data)["version"], 1)
        self.assertEqual(catalog.rollback(self.data, 0)["version"], 2)
        self.assertEqual(catalog.load_catalog(self.data)["detectors"], [])
        (evidence_dir / "incident-1.json").unlink()
        with self.assertRaisesRegex(catalog.CatalogError, "Cannot read catalog"):
            catalog.promote(self.data, candidate)


if __name__ == "__main__":
    unittest.main()
