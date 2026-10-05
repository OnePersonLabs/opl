"""Owned contracts: preserve human input, scoped evidence, and explicit integration.

These tests use deterministic local fixtures only. They never invoke a model.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins/opl/skills/human-collaboration/scripts"
sys.path.insert(0, str(SCRIPTS))
from inbox import Conflict, Inbox, InboxError
from server import HumanServer, notify


def spec(title="Where does the decision belong?", **changes):
    return {"title": title, "summary": "Separate retained evidence from bounded views.",
            "why_now": "Callers have not yet adopted this boundary.", "brief": "# Ownership\n\nReview the boundary, not just the code.",
            "decision": True, **changes}


def result(**changes):
    return {"text": "Separated the two responsibilities.", "disposition": "adopted",
            "source_review": "Reviewed the current fixture; this is not implementation proof.",
            "references": ["docs/decision.md"], **changes}


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.inbox = Inbox(self.workspace)
        self.inbox.init("root-1")

    def publish(self, **changes):
        return self.inbox.publish(spec(**changes), "root-1")

    def submit(self, item, key="request-1", body="Keep the evidence; bound the views."):
        return self.inbox.submit(item["id"], item["viewed_revision"], body, key)

    def test_file_save_is_not_submission_and_mtime_is_not_the_protocol(self):
        item = self.publish()
        path = self.workspace / item["brief_path"]
        stamp = path.stat().st_mtime_ns
        self.assertEqual(item["published_mtime_ns"], str(stamp))
        path.write_text(path.read_text() + "My answer", encoding="utf-8")
        os.utime(path, ns=(stamp, stamp))
        self.assertTrue(self.inbox.get(item["id"])["drafts"]["file_pending"])
        self.assertEqual(self.inbox.snapshot()["pending"], [])
        receipt = self.inbox.submit_file(item["id"])
        self.assertEqual(receipt["body"], "My answer")
        self.assertEqual(self.inbox.submit_file(item["id"])["id"], receipt["id"])

    def test_crlf_brief_and_editor_reply_remain_submittable(self):
        item = self.publish(brief="# Review\r\n\r\nKeep the evidence.\r\n")
        path = self.workspace / item["brief_path"]
        path.write_bytes((path.read_text() + "Separate the lifetimes.\n").replace("\n", "\r\n").encode())
        receipt = self.inbox.submit_file(item["id"])
        self.assertEqual(receipt["body"], "Separate the lifetimes.\n")

    def test_restart_duplicate_delivery_claim_and_outcome(self):
        item = self.publish()
        receipt = self.submit(item)
        restarted = Inbox(self.workspace)
        self.assertEqual(restarted.submit(item["id"], 1, receipt["body"], "request-1")["id"], receipt["id"])
        self.assertTrue(restarted.claim(receipt["id"], "root-1")["claimed_now"])
        self.assertFalse(restarted.claim(receipt["id"], "root-1")["claimed_now"])
        first = restarted.outcome(receipt["id"], result(), "root-1")
        self.assertEqual(restarted.outcome(receipt["id"], result(), "root-1"), first)
        self.assertEqual(restarted.get(item["id"])["state"], "resolved")
        self.assertEqual(restarted.snapshot()["pending"], [])
        self.assertTrue((self.inbox.root / "items" / item["id"] / "submissions" / f"{receipt['id']}.md").exists())

    def test_idempotency_key_cannot_be_reused_for_other_content(self):
        item = self.publish(); self.submit(item)
        with self.assertRaises(Conflict): self.submit(item, body="Different answer")

    def test_explicit_claim_and_source_review_are_required(self):
        receipt = self.submit(self.publish())
        with self.assertRaises(Conflict): self.inbox.outcome(receipt["id"], result(), "root-1")
        self.inbox.claim(receipt["id"], "root-1")
        with self.assertRaises(InboxError): self.inbox.outcome(receipt["id"], result(source_review=""), "root-1")

    def test_draft_compare_and_swap_preserves_other_device(self):
        item = self.publish()
        def save(body):
            try: return self.inbox.save_draft(item["id"], 1, body, 0)
            except Conflict: return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(save, ["Phone draft", "Laptop draft"]))
        self.assertEqual(sum(reply is not None for reply in replies), 1)
        self.assertIn(Inbox(self.workspace).get(item["id"])["drafts"]["web"]["body"], ["Phone draft", "Laptop draft"])
        self.assertEqual(self.inbox.snapshot()["pending"], [])

    def test_phone_draft_never_rewrites_editor_file(self):
        item = self.publish(); path = self.workspace / item["brief_path"]
        path.write_text(path.read_text() + "Editor draft", encoding="utf-8")
        before = path.read_bytes()
        self.inbox.save_draft(item["id"], 1, "Phone draft", 0)
        self.inbox.refresh()
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(self.inbox.get(item["id"])["drafts"]["file_pending"])

    def test_active_or_drafted_item_cannot_be_revised_or_retired(self):
        item = self.publish(); self.inbox.move(item["id"], "start")
        with self.assertRaises(Conflict): self.inbox.revise(item["id"], spec(), "new plan", "root-1")
        with self.assertRaises(Conflict): self.inbox.move(item["id"], "retire", "obsolete", thread="root-1")
        self.inbox.move(item["id"], "later", "Human deferred it")
        self.inbox.save_draft(item["id"], 1, "still working", 0)
        with self.assertRaises(Conflict): self.inbox.revise(item["id"], spec(), "new plan", "root-1")

    def test_second_active_item_requires_explicit_unpin(self):
        first = self.publish(); second = self.publish(title="Another boundary")
        self.inbox.move(first["id"], "start")
        with self.assertRaises(Conflict): self.inbox.move(second["id"], "start")
        self.inbox.move(first["id"], "later", "Switching focus")
        self.assertEqual(self.inbox.move(second["id"], "start")["state"], "active")

    def test_queue_actions_cannot_prepare_candidates_without_the_root(self):
        for action in ("later", "retire"):
            with self.subTest(action=action):
                item = self.publish(state="candidate")
                self.inbox.move(item["id"], action, "Not ready for review", thread="root-1")
                with self.assertRaises(Conflict):
                    self.inbox.move(item["id"], "ready", "Human reopening", thread="worker")
                with self.assertRaises(Conflict):
                    self.inbox.move(item["id"], "start")
                with self.assertRaises(Conflict):
                    self.submit(item, key=action)
                self.inbox.move(item["id"], "ready", "Review context prepared", thread="root-1")
                self.assertEqual(self.inbox.move(item["id"], "start")["state"], "active")
                self.submit(item, key=action)

    def test_revising_to_candidate_requires_new_root_preparation(self):
        item = self.publish()
        revised = self.inbox.revise(item["id"], spec(state="candidate"), "Needs more context", "root-1")
        with self.assertRaises(Conflict):
            self.submit(revised)
        self.inbox.move(item["id"], "ready", "Context completed", thread="root-1")
        self.assertEqual(self.submit(revised)["revision"], revised["viewed_revision"])

    def test_ranking_keeps_all_items_and_stable_ids(self):
        items = [self.publish(title=f"Decision {i}", priority=i+10) for i in range(6)]
        self.inbox.move(items[-1]["id"], "rank", "Expensive dependency approaching", priority=0, thread="root-1")
        ranked = self.inbox.snapshot()["items"]
        self.assertEqual(ranked[0]["id"], items[-1]["id"])
        self.assertEqual(len(ranked), 6)
        generated = (self.inbox.root / "INBOX.md").read_text()
        self.assertIn("## Later", generated)
        for item in items: self.assertIn(item["id"], generated)

    def test_settled_decisions_remain_in_the_decision_map(self):
        item = self.publish(); receipt = self.submit(item)
        self.inbox.claim(receipt["id"], "root-1"); self.inbox.outcome(receipt["id"], result(), "root-1")
        self.assertIn(item["id"], (self.inbox.root / "DECISIONS.md").read_text())

    def test_new_submission_is_not_cleared_by_an_older_outcome(self):
        item = self.publish(); first = self.submit(item); second = self.submit(item, "request-2", "Also separate the scheduler")
        self.inbox.claim(first["id"], "root-1"); self.inbox.outcome(first["id"], result(), "root-1")
        self.assertEqual(self.inbox.get(item["id"])["state"], "with_agent")
        self.assertEqual([row["id"] for row in self.inbox.snapshot()["pending"]], [second["id"]])

    def test_questions_return_to_same_item_after_explanation(self):
        item = self.publish(); receipt = self.inbox.submit(item["id"], 1, "Why this boundary?", "question-1", kind="question")
        self.inbox.claim(receipt["id"], "root-1")
        self.inbox.outcome(receipt["id"], result(disposition="explained"), "root-1")
        self.assertEqual(self.inbox.get(item["id"])["state"], "ready")
        self.assertEqual(len(self.inbox.snapshot()["items"]), 1)

    def test_source_snapshot_and_changed_context_are_distinct(self):
        path = self.workspace / "algorithm.py"; path.write_bytes(b"return old_policy\n")
        item = self.publish(sources=["algorithm.py"])
        path.write_bytes(b"return new_policy\n")
        receipt = self.submit(item)
        claim = self.inbox.claim(receipt["id"], "root-1")
        self.assertTrue(claim["sources"][0]["changed"])
        self.assertEqual(self.inbox.source(item["id"], 1, 0)[0], b"return old_policy\n")
        self.assertEqual(self.inbox.source(item["id"], 1, 0, live=True)[0], b"return new_policy\n")

    def test_old_revision_feedback_keeps_original_title_and_evidence(self):
        item = self.publish(title="Original question")
        self.inbox.revise(item["id"], spec(title="Revised question"), "Better framing", "root-1")
        self.inbox.save_draft(item["id"], 1, "Feedback on old framing", 0)
        receipt = self.inbox.submit(item["id"], 1, "Feedback on old framing", "old-rev")
        old = self.inbox.get(item["id"], 1)
        self.assertEqual(old["title"], "Original question")
        self.assertEqual(old["revision"], 2)
        self.assertEqual(receipt["revision"], 1)

    def test_older_draft_stays_visible_and_prevents_revision_and_closure(self):
        item = self.publish()
        current = self.inbox.revise(item["id"], spec(), "Better framing", "root-1")
        self.inbox.save_draft(item["id"], 1, "Still reviewing the original", 0)
        indexed = self.inbox.snapshot()["items"][0]
        self.assertTrue(indexed["has_draft"])
        self.assertEqual(indexed["draft_revisions"], [1])
        receipt = self.submit(current)
        self.inbox.claim(receipt["id"], "root-1")
        self.inbox.outcome(receipt["id"], result(), "root-1")
        self.assertEqual(self.inbox.get(item["id"])["state"], "ready")
        with self.assertRaises(Conflict):
            self.inbox.revise(item["id"], spec(), "Third framing", "root-1")
        old = self.inbox.submit(item["id"], 1, "Still reviewing the original", "original-reply")
        self.inbox.claim(old["id"], "root-1")
        self.inbox.outcome(old["id"], result(), "root-1")
        self.assertEqual(self.inbox.get(item["id"])["state"], "resolved")

    def test_editor_reply_on_closed_older_brief_returns_to_attention(self):
        item = self.publish()
        current = self.inbox.revise(item["id"], spec(), "Better framing", "root-1")
        receipt = self.submit(current)
        self.inbox.claim(receipt["id"], "root-1")
        self.inbox.outcome(receipt["id"], result(), "root-1")
        path = self.workspace / item["brief_path"]
        path.write_text(path.read_text(encoding="utf-8") + "A further question", encoding="utf-8")
        self.assertEqual(self.inbox.snapshot()["items"][0]["state"], "ready")
        self.assertEqual(self.inbox.get(item["id"])["state"], "ready")
        self.assertEqual(self.inbox.move(item["id"], "start")["state"], "active")
        self.assertEqual(self.inbox.move(item["id"], "later", "Continue later")["state"], "deferred")
        with self.assertRaises(Conflict):
            self.inbox.move(item["id"], "retire", "Done", thread="root-1")

    def test_source_paths_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / "secret.txt"; target.write_text("private")
            try: (self.workspace / "outside.txt").symlink_to(target)
            except OSError: self.skipTest("symlink creation unavailable")
            with self.assertRaises(InboxError): self.publish(sources=["outside.txt"])
        with self.assertRaises(InboxError): self.publish(sources=[str(self.inbox.db_path)])

    def test_hook_routes_only_to_owner_and_recovers_after_compaction(self):
        receipt = self.submit(self.publish())
        hook = {"session_id": "root-1", "hook_event_name": "PostToolUse"}
        self.assertEqual(self.inbox.hook({**hook, "session_id": "worker"}), {})
        self.assertIn(receipt["id"], json.dumps(self.inbox.hook(hook)))
        self.assertEqual(self.inbox.hook(hook), {})
        self.assertIn(receipt["id"], json.dumps(Inbox(self.workspace).hook({**hook, "hook_event_name": "SessionStart", "source": "compact"})))
        self.assertEqual(self.inbox.snapshot()["pending"][0]["state"], "submitted")

    def test_explicit_root_handoff_does_not_reset_claims(self):
        receipt = self.submit(self.publish()); self.inbox.claim(receipt["id"], "root-1")
        self.inbox.bind("root-2", "Previous root stopped; new session owns integration")
        with self.assertRaises(Conflict): self.inbox.claim(receipt["id"], "root-1")
        resumed = self.inbox.claim(receipt["id"], "root-2")
        self.assertFalse(resumed["claimed_now"])
        self.assertEqual(resumed["claimed_by"], "root-1")

    def test_committed_version_recovers_after_materialization_failure(self):
        with patch.object(self.inbox, "refresh", side_effect=OSError("simulated process failure")):
            with self.assertRaises(OSError): self.publish()
        restarted = Inbox(self.workspace); restarted.refresh()
        self.assertIn("# Reply", restarted.brief_path(1,1).read_text())

    def test_missing_human_file_is_not_silently_replaced_with_empty_reply(self):
        item = self.publish(); path = self.workspace / item["brief_path"]; path.unlink()
        with self.assertRaises(InboxError): self.inbox.refresh()
        self.assertFalse(path.exists())

    def test_body_edits_are_not_mistaken_for_a_reply(self):
        item = self.publish(); path = self.workspace / item["brief_path"]
        path.write_text(path.read_text().replace("Ownership", "Completely different question"))
        with self.assertRaises(Conflict): self.inbox.submit_file(item["id"])
        with self.assertRaises(Conflict): self.inbox.revise(item["id"], spec(), "new", "root-1")

    def test_notification_acceptance_does_not_mark_consumed_or_repeat(self):
        receipt = self.submit(self.publish())
        helper = SimpleNamespace(subprocess_argv=lambda args: args)
        with patch.dict(sys.modules, {"run_and_wake": helper}), patch("server.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="accepted", stderr="")) as run:
            self.assertEqual(notify(self.inbox, receipt["id"])["state"], "accepted")
            self.assertEqual(notify(self.inbox, receipt["id"])["state"], "accepted")
            self.assertEqual(run.call_count, 1)
            args = run.call_args.args[0]
            self.assertEqual(args[1:4], ["queue", "--thread", "root-1"])
            self.assertNotIn(receipt["body"], args[-1])
        self.assertEqual(self.inbox.snapshot()["pending"][0]["state"], "submitted")

    def test_unknown_notification_delivery_remains_inspectable(self):
        receipt = self.submit(self.publish())
        helper = SimpleNamespace(subprocess_argv=lambda args: args)
        with patch.dict(sys.modules, {"run_and_wake": helper}), patch("server.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 15)):
            self.assertEqual(notify(self.inbox, receipt["id"])["state"], "unknown")
        self.assertEqual(len(self.inbox.snapshot()["pending"]), 1)

    def test_unsupported_schema_fails_without_reinitializing(self):
        with closing(sqlite3.connect(self.inbox.db_path)) as db: db.execute("PRAGMA user_version=99")
        with self.assertRaises(InboxError): self.inbox.init("root-1")

    def test_human_initiated_contribution_is_atomic_and_idempotent(self):
        receipt = self.inbox.contribute("Review the scheduler", "It owns audible commitment.", "new-note")
        duplicate = self.inbox.contribute("Review the scheduler", "It owns audible commitment.", "new-note")
        self.assertEqual(receipt["id"], duplicate["id"])
        self.assertEqual(len(self.inbox.snapshot()["items"]), 1)
        self.assertEqual(len(self.inbox.snapshot()["pending"]), 1)
        with self.assertRaises(Conflict):
            self.inbox.contribute("Different premise", "It owns audible commitment.", "new-note")
        self.inbox.claim(receipt["id"], "root-1")
        self.inbox.outcome(receipt["id"], result(disposition="follow_up"), "root-1")
        self.assertEqual(self.inbox.get(receipt["item"])["state"], "ready")

    def test_cli_round_trip_and_inactive_hook(self):
        spec_file = self.workspace / "review.json"; spec_file.write_text(json.dumps(spec()))
        command = [sys.executable, "-B", str(SCRIPTS / "human.py"), "--workspace", str(self.workspace), "--thread", "root-1"]
        item = json.loads(subprocess.check_output([*command, "publish", str(spec_file)]))
        path = self.workspace / item["brief_path"]; path.write_text(path.read_text() + "CLI reply")
        receipt = json.loads(subprocess.check_output([*command, "submit", item["id"]]))
        self.assertEqual(receipt["body"], "CLI reply")
        pending = json.loads(subprocess.check_output([*command, "pending"]))
        self.assertNotIn("body", pending[0])
        with tempfile.TemporaryDirectory() as elsewhere:
            output = subprocess.check_output([sys.executable, "-B", str(SCRIPTS / "human.py"), "hook"], input=json.dumps({"cwd": elsewhere, "session_id": "new", "hook_event_name": "SessionStart"}).encode())
            self.assertEqual(json.loads(output), {})
            self.assertFalse((Path(elsewhere) / ".human").exists())


class HttpTests(InboxTests):
    # Inherit setup, not the whole core suite a second time.
    def setUp(self):
        super().setUp()
        self.server = HumanServer(self.inbox, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None,
                    headers={"Authorization": "Bearer " + self.server.token, "Content-Type": "application/json", **(headers or {})})
        return urllib.request.urlopen(request, timeout=3)

    def test_http_requires_auth_and_same_origin(self):
        for headers in ({"Authorization": "Bearer wrong"}, {"Origin": "http://evil.invalid"}, {"Host": "evil.invalid:1234"}):
            with self.assertRaises(urllib.error.HTTPError) as error: self.request("/api/inbox", headers=headers)
            self.assertIn(error.exception.code, (400,401))

    def test_http_cannot_publish_resolve_or_read_arbitrary_paths(self):
        item = self.publish()
        with self.assertRaises(urllib.error.HTTPError): self.request("/api/action", {"id":item["id"], "action":"retire", "reason":"not allowed"})
        with self.assertRaises(urllib.error.HTTPError): self.request("/api/source?path=/etc/passwd")
        self.assertEqual(self.inbox.get(item["id"])["state"], "ready")

    def test_http_submit_and_duplicate_request(self):
        item = self.publish(); payload = {"id":item["id"], "revision":1, "body":"Phone reply", "request_id":"same"}
        first = json.load(self.request("/api/submit", payload))
        second = json.load(self.request("/api/submit", payload))
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.inbox.snapshot()["pending"]), 1)


if __name__ == "__main__":
    # Explicit loading avoids inheriting the core test methods into HttpTests.
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(InboxTests))
    suite.addTests(HttpTests(name) for name in dir(HttpTests) if name.startswith("test_http_"))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not outcome.wasSuccessful())
