#!/usr/bin/env python3
"""Finite fixture checks for the audit ledger and bounded reader packets."""

from __future__ import annotations

from contextlib import closing
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PATH = ROOT / "plugins/opl/skills/slop-buster/scripts/slop_audit.py"
SPEC = importlib.util.spec_from_file_location("slop_audit", PATH)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)

SESSION = "11111111-1111-4111-8111-111111111111"


def item(timestamp: str, kind: str, payload: dict) -> dict:
    return {"timestamp": timestamp, "type": kind, "payload": payload}


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        folder = self.home / "sessions/2026/09/27"
        folder.mkdir(parents=True)
        self.path = folder / f"rollout-{SESSION}.jsonl"
        self.repo = self.root / "data"
        self.config = {"data_repo": str(self.repo), "source_homes": [str(self.home)]}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, *records: dict) -> None:
        self.path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def fixture(self, body: str = "Answer") -> None:
        self.write(
            item("2026-09-27T00:00:00Z", "session_meta", {"id": SESSION}),
            item("2026-09-27T00:00:01Z", "event_msg", {"type": "user_message", "message": "Ask"}),
            item("2026-09-27T00:00:02Z", "event_msg", {"type": "agent_message", "message": body, "phase": "final_answer"}),
            item("2026-09-27T00:00:03Z", "event_msg", {"type": "user_message", "message": "Please correct it"}),
        )

    def test_full_chunks_resume_commit_and_evidence(self) -> None:
        body = "A" * 9000 + " wrong statement " + "B" * 9000
        self.fixture(body)
        first = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                              until="2026-09-27T23:00:00Z")
        self.assertEqual(first["indexed"], 3)
        self.assertEqual(first["staged"], 5)
        resumed = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                                until="2026-09-27T23:00:00Z")
        self.assertEqual(resumed["run_id"], first["run_id"])
        self.assertEqual(resumed["indexed"], 0)
        conn = audit._connect(self.repo)
        try:
            source = audit.source_progress(conn, first["run_id"], str(self.path))
            self.assertEqual(source["indexed"], 3)
            self.assertEqual(source["pending"], 5)
            with self.assertRaises(audit.AuditError):
                audit.finish(conn, self.repo, first["run_id"])
            reviewed = []
            while True:
                packet = audit.next_batch(conn, first["run_id"], "worker")
                if not packet["batch_id"]:
                    break
                self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False)), audit.DEFAULT_PACKET_CHARS)
                again = audit.next_batch(conn, first["run_id"], "worker")
                self.assertEqual(again["batch_id"], packet["batch_id"])
                self.assertTrue(all(len(i["body"]) <= audit.PART_CHARS for i in packet["items"]))
                self.assertTrue(all(i["next_user"]["excerpt"] == "Please correct it"
                                    for i in packet["items"] if i["role"] == "assistant"))
                verdicts = []
                incidents = []
                for chunk in packet["items"]:
                    reviewed.append((chunk["role"], chunk["part"]))
                    bad = " wrong statement " in chunk["body"]
                    verdicts.append({"chunk_id": chunk["chunk_id"], "verdict": "incident" if bad else "clean"})
                    if bad:
                        incidents.append({"chunk_id": chunk["chunk_id"], "category": "claim",
                                          "severity": "medium", "explanation": "Unsupported claim",
                                          "quote": " wrong statement "})
                report = {"verdicts": verdicts, "incidents": incidents}
                committed = audit.record(conn, first["run_id"], packet["batch_id"], report)
                retry = audit.record(conn, first["run_id"], packet["batch_id"], report)
                self.assertTrue(retry["already_committed"])
                self.assertEqual(retry["incident_ids"], committed["incident_ids"])
            self.assertEqual(sorted(reviewed), [("assistant", 0), ("assistant", 1),
                                                ("assistant", 2), ("user", 0), ("user", 0)])
            result = audit.finish(conn, self.repo, first["run_id"])
            self.assertEqual(result["completed"], 5)
            self.assertEqual(result["evidence_count"], 1)
            evidence = next((self.repo / "evidence").glob("*.json"))
            snapshot = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["body"], body)
            self.assertEqual(snapshot["path"], str(self.path.resolve()))
            self.assertEqual(snapshot["raw_line"], 3)
            self.assertEqual(audit.show(conn, snapshot["incident_id"], chars=100)["next_start"], 100)
        finally:
            conn.close()

    def test_registry_excludes_explicit_audit_session(self) -> None:
        self.fixture()
        audit.register_session(self.repo, SESSION)
        result = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                               until="2026-09-27T23:00:00Z")
        self.assertEqual(result["indexed"], 0)
        self.assertEqual(result["staged"], 0)

    def test_filtered_waits_for_full_and_manual_capture_is_idempotent(self) -> None:
        self.fixture("Bad answer")
        pending = audit.prepare(self.config, mode="filtered")
        self.assertTrue(pending["discovery_required"])
        self.assertEqual(pending["indexed"], 0)
        full = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                             until="2026-09-27T23:00:00Z")
        conn = audit._connect(self.repo)
        try:
            event = conn.execute("SELECT event_id FROM events WHERE role='assistant'").fetchone()[0]
            first = audit.capture(conn, self.repo, event, quote="Bad answer", category="claim",
                                  severity="low", explanation="Wrong claim")
            second = audit.capture(conn, self.repo, event, quote="Bad answer", category="claim",
                                   severity="low", explanation="Wrong claim")
            self.assertEqual(first["incident_id"], second["incident_id"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0], 1)
            self.assertEqual(len(list((self.repo / "evidence").glob("*.json"))), 1)
            self.assertEqual(audit.show_event(conn, event)["previous_user"]["raw_line"], 2)
            self.assertEqual(audit.latest_progress(conn)["mode"], "manual")
        finally:
            conn.close()

    def test_explicit_claude_session_uses_same_bounded_queue(self) -> None:
        claude = self.root / "claude" / f"{SESSION}.jsonl"
        claude.parent.mkdir()
        records = [
            {"type": "user", "sessionId": SESSION, "timestamp": "2026-09-27T00:00:01Z",
             "message": {"content": "Question"}},
            {"type": "assistant", "sessionId": SESSION, "timestamp": "2026-09-27T00:00:02Z",
             "message": {"content": [{"type": "text", "text": "Answer"},
                                     {"type": "tool_use", "text": "do not index"}]}},
        ]
        claude.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        result = audit.prepare(self.config, mode="full", session=str(claude),
                               since="2026-09-27T00:00:00Z", until="2026-09-27T23:00:00Z")
        self.assertEqual(result["indexed"], 2)
        self.assertEqual(result["staged"], 2)
        conn = audit._connect(self.repo)
        try:
            packet = audit.next_batch(conn, result["run_id"])
            self.assertEqual({item["body"] for item in packet["items"]}, {"Question", "Answer"})
            self.assertTrue(all(item["path"] == str(claude.resolve()) for item in packet["items"]))
        finally:
            conn.close()

    def test_filtered_uses_full_baseline_and_reviews_only_new_match(self) -> None:
        self.fixture("Initial answer")
        full = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                             until="2026-09-27T00:00:10Z")
        conn = audit._connect(self.repo)
        try:
            while True:
                packet = audit.next_batch(conn, full["run_id"])
                if not packet["batch_id"]:
                    break
                audit.record(conn, full["run_id"], packet["batch_id"], {
                    "verdicts": [{"chunk_id": i["chunk_id"], "verdict": "clean"} for i in packet["items"]],
                    "incidents": [],
                })
            audit.finish(conn, self.repo, full["run_id"])
        finally:
            conn.close()

        repeated_full = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                                      until="2026-09-27T00:00:10Z", reason="explicit second review")
        self.assertNotEqual(repeated_full["run_id"], full["run_id"])
        self.assertEqual(repeated_full["staged"], 3)

        catalog = self.repo / "catalog"
        catalog.mkdir()
        (catalog / "active.json").write_text(json.dumps({
            "schema_version": 1, "version": 1, "detectors": [{
                "id": "wrong_claim", "kind": "literal", "pattern": "wrong claim",
                "roles": ["assistant"], "phases": ["final_answer"], "events": [],
                "context": {}, "exclude": [], "steering": "verify_claim", "evidence_ids": ["fixture"],
            }, {
                "id": "user_correction", "kind": "literal", "pattern": "please correct",
                "roles": ["user"], "phases": ["user"], "events": [],
                "context": {}, "exclude": [], "steering": "examine_premise", "evidence_ids": ["fixture"],
            }],
        }), encoding="utf-8")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item("2026-09-27T00:00:11Z", "event_msg", {
                "type": "agent_message", "message": "A wrong claim", "phase": "final_answer",
            })) + "\n")
            handle.write(json.dumps(item("2026-09-27T00:00:12Z", "event_msg", {
                "type": "user_message", "message": "Please correct the claim",
            })) + "\n")
        filtered = audit.prepare(self.config, mode="filtered", until="2026-09-27T00:00:20Z")
        self.assertEqual(filtered["staged"], 2)
        self.assertFalse(filtered["discovery_required"])
        self.assertEqual(filtered["since"], full["since"])
        conn = audit._connect(self.repo)
        try:
            packet = audit.next_batch(conn, filtered["run_id"])
            self.assertEqual([i["body"] for i in packet["items"]],
                             ["Please correct the claim", "A wrong claim"])
            self.assertEqual([i["matches"][0]["pattern_id"] for i in packet["items"]],
                             ["user_correction", "wrong_claim"])
        finally:
            conn.close()

    def test_user_correction_incident_keeps_assistant_attribution(self) -> None:
        self.fixture("The prior claim")
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        conn = audit._connect(self.repo)
        try:
            while True:
                packet = audit.next_batch(conn, run["run_id"])
                if not packet["batch_id"]:
                    break
                verdicts, incidents = [], []
                for chunk in packet["items"]:
                    issue = chunk["body"] == "Please correct it"
                    verdicts.append({"chunk_id": chunk["chunk_id"], "verdict": "incident" if issue else "clean"})
                    if issue:
                        incidents.append({"chunk_id": chunk["chunk_id"], "category": "correction",
                                          "severity": "medium", "explanation": "User corrected answer",
                                          "quote": "Please correct it", "user_summary": "The user asked for a correction."})
                audit.record(conn, run["run_id"], packet["batch_id"],
                             {"verdicts": verdicts, "incidents": incidents})
            audit.finish(conn, self.repo, run["run_id"])
            evidence = json.loads(next((self.repo / "evidence").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(evidence["role"], "user")
            self.assertEqual(evidence["attributed_assistant"]["body"], "The prior claim")
            self.assertEqual(evidence["attributed_assistant"]["raw_line"], 3)
            listed = audit.list_incidents(conn, run["run_id"])
            self.assertEqual(listed["summary"], [{"category": "correction", "count": 1}])
            self.assertEqual(len(listed["items"]), 1)
        finally:
            conn.close()

    def test_malformed_complete_line_blocks_finish_until_repaired(self) -> None:
        self.fixture("Answer")
        original = self.path.read_text(encoding="utf-8")
        self.path.write_text(original + "{broken json}\n", encoding="utf-8")
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        self.assertEqual(run["progress"]["source_gaps"],
                         [{"kind": "malformed", "sources": 1, "amount": 1}])
        conn = audit._connect(self.repo)
        try:
            with self.assertRaisesRegex(audit.AuditError, "source gaps"):
                audit.finish(conn, self.repo, run["run_id"])
        finally:
            conn.close()
        self.path.write_text(original, encoding="utf-8")
        resumed = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                                until="2026-09-27T23:00:00Z")
        self.assertEqual(resumed["run_id"], run["run_id"])
        self.assertEqual(resumed["progress"]["source_gaps"], [])

    def test_missing_home_is_visible_gap(self) -> None:
        self.config["source_homes"] = [str(self.root / "missing-home")]
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        self.assertEqual(run["progress"]["source_gaps"][0]["kind"], "missing_home")
        conn = audit._connect(self.repo)
        try:
            with self.assertRaisesRegex(audit.AuditError, "source gaps"):
                audit.finish(conn, self.repo, run["run_id"])
        finally:
            conn.close()

    def test_live_partial_tail_is_pending_then_clears(self) -> None:
        self.fixture("Answer")
        original = self.path.read_bytes()
        self.path.write_bytes(original + b'{"timestamp":')
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        self.assertEqual(run["progress"]["source_gaps"][0]["kind"], "partial_tail")
        self.path.write_bytes(original)
        resumed = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                                until="2026-09-27T23:00:00Z")
        self.assertEqual(resumed["progress"]["source_gaps"], [])

    def test_partial_tail_gap_clears_after_archive_move(self) -> None:
        self.fixture("Answer")
        original = self.path.read_bytes()
        self.path.write_bytes(original + b'{"timestamp":')
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        archived = self.home / "archived_sessions" / self.path.name
        archived.parent.mkdir()
        archived.write_bytes(original)
        self.path.unlink()
        resumed = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                                until="2026-09-27T23:00:00Z")
        self.assertEqual(resumed["run_id"], run["run_id"])
        self.assertEqual(resumed["progress"]["source_gaps"], [])

    def test_rewrite_supersedes_stale_pending_chunk(self) -> None:
        self.fixture("Old answer")
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        self.fixture("New answer")
        resumed = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                                until="2026-09-27T23:00:00Z")
        self.assertEqual(resumed["run_id"], run["run_id"])
        self.assertEqual(resumed["progress"]["superseded"], 1)
        conn = audit._connect(self.repo)
        try:
            old = conn.execute("SELECT source_valid FROM events WHERE body='Old answer'").fetchone()[0]
            self.assertEqual(old, 0)
            packet = audit.next_batch(conn, run["run_id"])
            self.assertNotIn("Old answer", [item["body"] for item in packet["items"]])
            self.assertIn("New answer", [item["body"] for item in packet["items"]])
        finally:
            conn.close()

    def test_rewrite_marks_existing_evidence_invalidated(self) -> None:
        self.fixture("Old claim")
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        conn = audit._connect(self.repo)
        try:
            while True:
                packet = audit.next_batch(conn, run["run_id"])
                if not packet["batch_id"]:
                    break
                verdicts, incidents = [], []
                for chunk in packet["items"]:
                    issue = chunk["body"] == "Old claim"
                    verdicts.append({"chunk_id": chunk["chunk_id"], "verdict": "incident" if issue else "clean"})
                    if issue:
                        incidents.append({"chunk_id": chunk["chunk_id"], "category": "claim",
                                          "severity": "medium", "explanation": "Claim failed",
                                          "quote": "Old claim"})
                audit.record(conn, run["run_id"], packet["batch_id"],
                             {"verdicts": verdicts, "incidents": incidents})
            audit.finish(conn, self.repo, run["run_id"])
            incident_id = audit.list_incidents(conn, run["run_id"])["items"][0]["incident_id"]
        finally:
            conn.close()
        self.fixture("New claim")
        audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                      until="2026-09-27T23:00:00Z")
        conn = audit._connect(self.repo)
        try:
            self.assertEqual(audit.show(conn, incident_id)["source_valid"], 0)
            marker = self.repo / "evidence" / f"{incident_id}.invalidated.json"
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8"))["incident_id"], incident_id)
        finally:
            conn.close()

    def test_previously_indexed_source_disappearance_blocks_finish(self) -> None:
        self.fixture("Answer")
        run = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                            until="2026-09-27T23:00:00Z")
        self.path.unlink()
        resumed = audit.prepare(self.config, mode="full", since="2026-09-27T00:00:00Z",
                                until="2026-09-27T23:00:00Z")
        self.assertEqual(resumed["run_id"], run["run_id"])
        self.assertEqual(resumed["progress"]["source_gaps"],
                         [{"kind": "missing_source", "sources": 1, "amount": 1}])
        conn = audit._connect(self.repo)
        try:
            with self.assertRaisesRegex(audit.AuditError, "source gaps"):
                audit.finish(conn, self.repo, run["run_id"])
        finally:
            conn.close()

    def test_hook_feedback_import_is_metadata_only_and_idempotent(self) -> None:
        source = self.home / "cache" / "slop-buster" / "hooks.sqlite3"
        source.parent.mkdir(parents=True)
        with closing(sqlite3.connect(source)) as db:
            db.execute("""CREATE TABLE alerts(alert_id TEXT,session_id TEXT,turn_id TEXT,
                pattern_id TEXT,catalog_version INTEGER,evidence_ids TEXT,event TEXT,
                source_path TEXT,source_size INTEGER,created_at REAL,feedback TEXT,feedback_at REAL)""")
            db.execute("INSERT INTO alerts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                "alert-1", SESSION, "turn-1", "wrong_claim", 3, '["EV-1"]',
                "Stop", str(self.path), 17, 1.0, None, None,
            ))
            db.commit()
        first = audit.import_feedback(self.config)
        self.assertEqual(first["counts"]["total"], 1)
        self.assertEqual(first["patterns"][0]["catalog_version"], 3)
        self.assertEqual(first["items"][0]["evidence_ids"], ["EV-1"])
        self.assertNotIn("body", first["items"][0])
        with closing(sqlite3.connect(source)) as db:
            db.execute("UPDATE alerts SET feedback='true',feedback_at=2.0 WHERE alert_id='alert-1'")
            db.commit()
        rated = audit.import_feedback(self.config)
        self.assertEqual(rated["counts"]["pending_review"], 1)
        conn = audit._connect(self.repo)
        try:
            self.assertEqual(audit.acknowledge_feedback(conn, "alert-1")["counts"]["pending_review"], 0)
        finally:
            conn.close()
        audit.register_session(self.repo, SESSION)
        second = audit.import_feedback(self.config)
        self.assertEqual(second["counts"]["total"], 1)
        self.assertEqual(second["counts"]["confirmed"], 1)
        self.assertEqual(second["counts"]["audit_owned"], 1)
        self.assertEqual(second["items"][0]["source_path"], str(self.path))

    def test_existing_ledger_adds_report_hash_without_losing_batch(self) -> None:
        path = self.repo / ".runtime" / "audit.sqlite3"
        path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE batches(batch_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,claimed_at TEXT NOT NULL,lease_until TEXT NOT NULL,
                state TEXT NOT NULL)""")
            db.execute("INSERT INTO batches VALUES('batch-old','run-old','worker','a','b','claimed')")
            db.commit()
        conn = audit._connect(self.repo)
        try:
            row = conn.execute("SELECT batch_id,report_hash FROM batches").fetchone()
            self.assertEqual(row["batch_id"], "batch-old")
            self.assertIsNone(row["report_hash"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
