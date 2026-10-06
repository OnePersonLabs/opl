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
from catalog import Catalog
from service import connect, receipt, save_receipt, connection_links
from network import lan_address


def spec(title="Where does the decision belong?", **changes):
    return {"title": title, "summary": "Separate retained evidence from bounded views.",
            "why_now": "Callers have not yet adopted this boundary.", "brief": "# Ownership\n\nReview the boundary, not just the code.",
            "decision": True, **changes}


def result(**changes):
    return {"text": "Separated the two responsibilities.", "disposition": "adopted",
            "source_review": "Reviewed the current fixture; this is not implementation proof.",
            "references": ["docs/decision.md"], **changes}


def questions():
    return [{"id": "ownership", "prompt": "Where should this decision belong?", "options": ["Keep it with the caller", "Move it into the service", "Defer the boundary"]},
            {"id": "evidence", "prompt": "Which evidence should we retain?", "options": ["Keep the source snapshot", "Keep the result only", "Keep both views"]}]


class NetworkTests(unittest.TestCase):
    def test_windows_lan_selection_uses_first_private_candidate(self):
        response = SimpleNamespace(stdout=json.dumps(["127.0.0.1", "169.254.1.2", "100.64.1.2", "192.168.8.223", "10.0.0.2"]))
        with patch("network.os.name", "nt"), patch("network.subprocess.run", return_value=response):
            self.assertEqual(lan_address(), "192.168.8.223")

    def test_lan_selection_reports_missing_and_failed_discovery(self):
        with patch("network.os.name", "nt"), patch("network.subprocess.run", return_value=SimpleNamespace(stdout="[]")):
            with self.assertRaisesRegex(InboxError, "choose --host explicitly"):
                lan_address()
        with patch("network.os.name", "nt"), patch("network.subprocess.run", side_effect=subprocess.TimeoutExpired("discovery", 15)):
            with self.assertRaisesRegex(InboxError, "cannot inspect LAN adapters"):
                lan_address()

    def test_posix_lan_selection_uses_local_source_address(self):
        with patch("network.os.name", "posix"), patch("network.socket.socket") as factory:
            route = factory.return_value.__enter__.return_value
            route.getsockname.return_value = ("172.20.1.3", 1234)
            self.assertEqual(lan_address(), "172.20.1.3")
            route.send.assert_not_called()
            route.sendto.assert_not_called()

    def test_phone_links_match_the_actual_bind_and_keep_pairing_token(self):
        from urllib.parse import urlsplit
        for host in ("192.168.8.223", "fd00::123"):
            links = connection_links(host, 2345, "private-token")
            parsed = urlsplit(links["lan_url"])
            self.assertEqual(parsed.hostname, host)
            self.assertEqual(parsed.port, 2345)
            self.assertEqual(parsed.fragment, "token=private-token")
            self.assertEqual(links["lan_ip"], host)
        local = connection_links("127.0.0.1", 2345, "private-token")
        self.assertEqual(local["access"], "local-only")
        self.assertIsNone(local["lan_url"])
        self.assertIsNone(local["lan_ip"])
        self.assertEqual(urlsplit(connection_links("0.0.0.0", 2345, "private-token")["url"]).hostname, "127.0.0.1")


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        runtime = patch.dict(os.environ, {"OPL_HUMAN_RUNTIME": str(self.workspace / "private-runtime")})
        runtime.start()
        self.addCleanup(runtime.stop)
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
        before = self.inbox.snapshot()["sessions"]
        with self.assertRaises(Conflict):
            self.inbox.bind("root-2", "Previous root stopped; new session owns integration", "root-1")
        self.assertEqual(self.inbox.snapshot()["sessions"], before)
        self.assertEqual(self.inbox.get(receipt["item"])["owner_thread"], "root-1")
        self.inbox.init("root-2")
        self.inbox.bind("root-2", "Previous root stopped; new session owns integration", "root-1")
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

    def test_schema_one_migration_preserves_editor_drafts_claims_and_outcomes(self):
        first = self.publish(); accepted = self.submit(first)
        self.inbox.claim(accepted["id"], "root-1")
        saved = self.inbox.outcome(accepted["id"], result(), "root-1")
        second = self.publish(title="Unfinished decision")
        pending = self.submit(second, "unfinished")
        self.inbox.claim(pending["id"], "root-1")
        self.inbox.save_draft(second["id"], 1, "Phone draft", 0)
        brief = self.workspace / second["brief_path"]
        brief.write_text(brief.read_text() + "Editor draft", encoding="utf-8")
        before = brief.read_bytes()
        with closing(sqlite3.connect(self.inbox.db_path)) as db:
            for number, raw in db.execute("SELECT id,doc FROM items").fetchall():
                value = json.loads(raw); value.pop("owner_thread")
                db.execute("UPDATE items SET doc=? WHERE id=?", (json.dumps(value), number))
            db.execute("DROP TABLE sessions"); db.execute("PRAGMA user_version=1")
            db.execute("DROP TABLE questions")
            db.execute("ALTER TABLE drafts DROP COLUMN answers")
            db.execute("ALTER TABLE submissions DROP COLUMN answers")
            db.commit()
        migrated = Inbox(self.workspace)
        migrated.init("root-2", "Second independent session")
        self.assertEqual(migrated.get(second["id"])["drafts"]["web"]["body"], "Phone draft")
        self.assertEqual(migrated.get(first["id"])["outcomes"], [saved])
        self.assertFalse(migrated.claim(pending["id"], "root-1")["claimed_now"])
        self.assertEqual(brief.read_bytes(), before)
        self.assertEqual(migrated.get(second["id"])["owner_thread"], "root-1")
        self.assertEqual(len(migrated.snapshot()["sessions"]), 2)

    def test_independent_sessions_isolate_mutations_hooks_notifications_and_handoffs(self):
        first = self.publish(); receipt1 = self.submit(first)
        self.inbox.claim(receipt1["id"], "root-1")
        self.inbox.init("root-2", "Another project session")
        second = self.inbox.publish(spec(title="Other question"), "root-2")
        receipt2 = self.submit(second, "other-session")
        for action in (
            lambda: self.inbox.claim(receipt1["id"], "root-2"),
            lambda: self.inbox.outcome(receipt1["id"], result(), "root-2"),
            lambda: self.inbox.revise(first["id"], spec(), "new framing", "root-2"),
            lambda: self.inbox.move(first["id"], "rank", "rank", 0, "root-2"),
        ):
            with self.assertRaises(Conflict): action()
        hook = self.inbox.hook({"session_id": "root-2", "hook_event_name": "SessionStart"})
        self.assertIn(receipt2["id"], json.dumps(hook)); self.assertNotIn(receipt1["id"], json.dumps(hook))
        self.assertEqual([row["id"] for row in self.inbox.snapshot("root-2")["pending"]], [receipt2["id"]])
        helper = SimpleNamespace(subprocess_argv=lambda args: args)
        with patch.dict(sys.modules, {"run_and_wake": helper}), patch("server.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="accepted", stderr="")) as run:
            notify(self.inbox, receipt2["id"])
            self.assertEqual(run.call_args.args[0][1:4], ["queue", "--thread", "root-2"])
        with self.assertRaises(Conflict): self.inbox.bind("root-3", "handoff")
        self.inbox.init("root-3")
        self.inbox.bind("root-3", "root-1 stopped", "root-1")
        self.assertEqual(self.inbox.get(second["id"])["owner_thread"], "root-2")
        self.assertEqual(self.inbox.claim(receipt1["id"], "root-3")["claimed_by"], "root-1")

    def test_catalog_orders_sessions_by_attention_and_keeps_chronological_versions(self):
        first = self.publish(title="Original title", priority=20)
        self.inbox.revise(first["id"], spec(title="New title", priority=20), "Clarify the question", "root-1")
        self.inbox.init("root-2", "Urgent work")
        second = self.inbox.publish(spec(title="Urgent decision", priority=5), "root-2")
        self.inbox.init("root-3", "Waiting for agent")
        third = self.inbox.publish(spec(title="Agent review"), "root-3")
        submitted = self.submit(third, "waiting")
        self.inbox.init("root-4", "Later work")
        self.inbox.publish(spec(state="candidate"), "root-4")
        catalog = Catalog(inboxes=[self.inbox])
        snapshot = catalog.snapshot()
        self.assertEqual([row["thread"] for row in snapshot["sessions"]], ["root-2", "root-1", "root-3", "root-4"])
        messages = snapshot["messages"]
        self.assertEqual([message["created"] for message in messages], sorted((message["created"] for message in messages), reverse=True))
        self.assertTrue(any(message["role"] == "you" and message["item"] == third["id"] for message in messages))
        titles = [message["title"] for message in messages if message["item"] == first["id"]]
        self.assertEqual(titles, ["New title", "Original title"])
        self.inbox.save_draft(second["id"], 1, "Draft is not conversation activity", 0)
        self.assertEqual(catalog.snapshot()["messages"], messages)
        self.inbox.claim(submitted["id"], "root-3")
        self.inbox.outcome(submitted["id"], result(), "root-3")
        self.assertEqual(catalog.snapshot()["messages"][0]["kind"], "adopted")

    def test_question_partial_answers_and_assumptions_do_not_claim_human_approval(self):
        item = self.publish(questions=questions())
        partial = self.inbox.submit(item["id"], 1, "", "one-answer", answers={"ownership": {"option": 2}})
        viewed = self.inbox.get(item["id"])
        self.assertEqual([question["state"] for question in viewed["questions"]], ["answered", "open"])
        self.assertEqual(viewed["state"], "with_agent")
        self.inbox.claim(partial["id"], "root-1")
        self.inbox.outcome(partial["id"], result(), "root-1")
        self.assertEqual(self.inbox.get(item["id"])["state"], "ready")
        assumed = self.inbox.assume(item["id"], ["evidence"], "No independent work remains; this choice is reversible", "root-1")
        self.assertEqual(assumed["state"], "answer_assumed")
        self.assertEqual(assumed["questions"][1]["answer"], {"option": 0})
        self.assertEqual(self.inbox.snapshot()["pending"], [])
        summary = self.inbox.snapshot()["sessions"][0]
        self.assertEqual((summary["needs_you"], summary["assumed"]), (0, 1))
        self.assertEqual(self.inbox.snapshot()["messages"][0]["kind"], "answer_assumed")
        corrected = self.inbox.submit(item["id"], 1, None, "human-correction", answers={"evidence": {"text": "Retain both and record their different roles"}})
        self.assertEqual(self.inbox.get(item["id"])["state"], "with_agent")
        self.assertEqual(corrected["answers"]["evidence"]["text"], "Retain both and record their different roles")
        self.assertIn("Which evidence", self.inbox.snapshot()["messages"][0]["text"])

    def test_assumptions_require_owner_current_revision_preparation_and_nonblocking_item(self):
        item = self.publish(questions=questions())
        self.inbox.init("root-2")
        with self.assertRaises(Conflict): self.inbox.assume(item["id"], ["ownership"], "Proceed", "root-2")
        with self.assertRaises(Conflict): self.inbox.assume(item["id"], ["ownership"], "Proceed", "root-1", revision=2)
        for changes in ({"blocking": True}, {"state": "candidate"}):
            blocked = self.publish(questions=questions(), **changes)
            with self.assertRaises(Conflict): self.inbox.assume(blocked["id"], ["ownership"], "Proceed", "root-1")
        with self.assertRaises(InboxError): self.inbox.assume(item["id"], ["ownership", "unknown"], "Proceed", "root-1")
        self.assertEqual(self.inbox.get(item["id"])["questions"][0]["state"], "open")
        with self.assertRaises(InboxError): self.inbox.assume(item["id"], ["ownership"], "", "root-1")

    def test_structured_answers_preserve_drafts_idempotency_and_reviewed_revision_definitions(self):
        item = self.publish(questions=questions())
        first = {"ownership": {"option": 0}}
        latest = {"ownership": {"option": 2}}
        self.inbox.save_draft(item["id"], 1, "", 0, first)
        with self.assertRaises(Conflict): self.inbox.save_draft(item["id"], 1, "", 0, latest)
        self.inbox.save_draft(item["id"], 1, "", 1, latest)
        submitted = self.inbox.submit(item["id"], 1, "", "structured-retry", answers=first)
        self.assertEqual(self.inbox.get(item["id"])["drafts"]["web"]["answers"], latest)
        self.assertEqual(self.inbox.submit(item["id"], 1, "", "structured-retry", answers=first)["id"], submitted["id"])
        with self.assertRaises(Conflict): self.inbox.submit(item["id"], 1, "", "structured-retry", answers=latest)
        matched = self.inbox.submit(item["id"], 1, "", "newer-answer", answers=latest)
        self.assertEqual(self.inbox.get(item["id"])["drafts"]["web"]["answers"], {})
        for receipt in (submitted, matched):
            self.inbox.claim(receipt["id"], "root-1"); self.inbox.outcome(receipt["id"], result(), "root-1")
        revised_questions = questions(); revised_questions[0]["options"][0] = "A new recommendation"
        self.inbox.revise(item["id"], spec(questions=revised_questions), "Reframe the questions", "root-1")
        old = self.inbox.get(item["id"], 1)
        self.assertEqual(old["questions"][0]["state"], "answered")
        first_option = questions()[0]["options"][0]
        self.assertEqual(old["submissions"][0]["questions"][0]["options"][0], first_option)
        self.assertNotEqual(self.inbox.get(item["id"])["questions"][0]["options"][0], first_option)
        self.inbox.save_draft(item["id"], 1, "", old["drafts"]["web"]["version"], {"evidence": {"option": 1}})
        self.assertEqual(self.inbox.snapshot()["items"][0]["draft_revisions"], [1])
        with self.assertRaises(Conflict): self.inbox.revise(item["id"], spec(questions=questions()), "Third revision", "root-1")

    def test_answers_validate_question_id_one_answer_shape_and_option_range(self):
        item = self.publish(questions=questions())
        for answers in ({"unknown": {"option": 0}}, {"ownership": {"option": 3}}, {"ownership": {"option": True}},
                        {"ownership": {"text": ""}}, {"ownership": {"option": 0, "text": "both"}}, []):
            with self.subTest(answers=answers), self.assertRaises(InboxError):
                self.inbox.submit(item["id"], 1, "", "invalid", answers=answers)
        with self.assertRaises(InboxError): self.inbox.submit(item["id"], 1, "", "empty")

    def test_explained_structured_answers_return_to_human_for_freeform_followup(self):
        item = self.publish(questions=questions())
        receipt = self.inbox.submit(item["id"], 1, "", "all-answered", answers={question["id"]: {"option": 0} for question in questions()})
        self.inbox.claim(receipt["id"], "root-1")
        self.inbox.outcome(receipt["id"], result(disposition="follow_up", text="The choices are clear. Can you describe the difficult caller?"), "root-1")
        self.assertEqual(self.inbox.get(item["id"])["state"], "ready")
        self.assertEqual(self.inbox.snapshot()["sessions"][0]["needs_you"], 1)

    def test_mixed_assumed_and_answered_questions_keep_explicit_human_followup(self):
        for disposition in ("explained", "follow_up"):
            with self.subTest(disposition=disposition):
                item = self.publish(questions=questions())
                reason = "No independent work remains; the boundary is reversible"
                self.inbox.assume(item["id"], ["ownership"], reason, "root-1")
                answers = {"evidence": {"option": 1}}
                receipt = self.inbox.submit(item["id"], 1, "", f"mixed-{disposition}", answers=answers)
                self.inbox.claim(receipt["id"], "root-1")
                followup = result(disposition=disposition, text="Which caller needs the exception?")
                self.inbox.outcome(receipt["id"], followup, "root-1")
                reopened = Inbox(self.workspace)
                self.assertEqual(reopened.get(item["id"])["state"], "ready")
                self.assertEqual(reopened.snapshot()["sessions"][0]["needs_you"], 1)
                reopened.submit(item["id"], 1, "", f"mixed-{disposition}", answers=answers)
                self.assertEqual(reopened.get(item["id"])["state"], "ready")
                reopened.move(item["id"], "start")
                self.assertEqual(reopened.assume(item["id"], ["ownership"], reason, "root-1")["state"], "active")
                response = reopened.submit(item["id"], 1, "The music scheduler caller", f"followup-response-{disposition}")
                self.assertEqual(reopened.get(item["id"])["state"], "with_agent")
                reopened.claim(response["id"], "root-1")
                reopened.outcome(response["id"], result(), "root-1")
                closed = reopened.get(item["id"])
                self.assertEqual(closed["state"], "answer_assumed")
                self.assertFalse(closed["human_follow_up"])
                self.assertEqual([question["state"] for question in closed["questions"]], ["answer_assumed", "answered"])
                reopened.outcome(receipt["id"], followup, "root-1")
                self.assertEqual(reopened.get(item["id"])["state"], "answer_assumed")

    def test_schema_two_migration_preserves_body_draft_claim_and_receipt(self):
        item = self.publish(); receipt = self.submit(item)
        self.inbox.claim(receipt["id"], "root-1")
        self.inbox.save_draft(item["id"], 1, "Keep this body draft", 0)
        with closing(sqlite3.connect(self.inbox.db_path)) as db:
            db.execute("DROP TABLE questions")
            db.execute("ALTER TABLE drafts DROP COLUMN answers")
            db.execute("ALTER TABLE submissions DROP COLUMN answers")
            db.execute("PRAGMA user_version=2"); db.commit()
        reopened = Inbox(self.workspace).get(item["id"])
        self.assertEqual(reopened["drafts"]["web"]["body"], "Keep this body draft")
        self.assertEqual(reopened["drafts"]["web"]["answers"], {})
        self.assertEqual(reopened["submissions"][0]["claimed_by"], "root-1")
        self.assertEqual(reopened["submissions"][0]["id"], receipt["id"])


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

    def test_http_registered_workspaces_disambiguate_duplicate_ids_and_contributions(self):
        other_path = self.workspace / "other"; other_path.mkdir()
        other = Inbox(other_path); other.init("root-2", "Other workspace")
        first = self.publish(); second = other.publish(spec(title="Other workspace decision"), "root-2")
        self.assertEqual(first["id"], second["id"])
        self.server.catalog.register(other)
        second_workspace = other.snapshot()["workspace_id"]
        with self.assertRaises(urllib.error.HTTPError): self.request("/api/item?id=H001")
        viewed = json.load(self.request(f"/api/item?id=H001&workspace={second_workspace}"))
        self.assertEqual(viewed["title"], second["title"])
        draft = {"workspace": second_workspace, "id": second["id"], "revision": 1, "body": "Other draft", "expected": 0}
        json.load(self.request("/api/draft", draft))
        self.assertEqual(self.inbox.get(first["id"])["drafts"]["web"]["body"], "")
        note = {"title": "New contribution", "body": "For this session", "request_id": "new-context"}
        with self.assertRaises(urllib.error.HTTPError): self.request("/api/contribute", note)
        response = json.load(self.request("/api/contribute", {**note, "session": viewed["session"]}))
        self.assertEqual(response["workspace_id"], second_workspace)
        self.assertEqual(other.get(response["item"])["owner_thread"], "root-2")
        with self.assertRaises(urllib.error.HTTPError): self.request("/api/item?id=H001&workspace=/etc/passwd")

    def test_http_connect_reuses_verified_ready_service_without_starting_process(self):
        catalog = Catalog(self.workspace / "private-runtime")
        catalog.register(self.inbox)
        self.server.catalog = catalog
        legacy = receipt(self.server, "127.0.0.1", catalog)
        for field in ("lan_ip", "lan_url", "access"):
            legacy.pop(field)
        save_receipt(catalog, legacy)
        with patch("service.subprocess.Popen") as start:
            connected = connect(self.inbox, port=self.server.server_port, catalog=catalog)
            self.assertTrue(connected["reused"])
            self.assertIn("#token=", connected["url"])
            self.assertEqual(connected["access"], "local-only")
            self.assertIsNone(connected["lan_url"])
            start.assert_not_called()

    def test_http_connect_reports_only_a_verified_service_after_lazy_launch(self):
        catalog = Catalog(self.workspace / "private-runtime")
        catalog.register(self.inbox)
        live = receipt(self.server, "127.0.0.1", catalog)
        child = SimpleNamespace(pid=live["pid"], poll=lambda: None)
        with patch("service.ready", side_effect=[None, live]), patch("service.subprocess.Popen", return_value=child) as start:
            connected = connect(self.inbox, port=self.server.server_port, catalog=catalog)
            self.assertEqual(connected["url"], live["url"])
            arguments = start.call_args.args[0]
            self.assertEqual(arguments[arguments.index("--port") + 1], str(self.server.server_port))
            self.assertNotIn("shell", start.call_args.kwargs)
        failed = SimpleNamespace(pid=1, returncode=2, poll=lambda: 2)
        with patch("service.ready", return_value=None), patch("service.subprocess.Popen", return_value=failed):
            with self.assertRaisesRegex(InboxError, "failed to start"):
                connect(self.inbox, port=self.server.server_port, catalog=catalog)

    def test_http_unavailable_workspace_keeps_healthy_reads_and_registry_recovery(self):
        catalog = Catalog(self.workspace / "private-runtime")
        healthy = self.publish(); healthy_id = catalog.register(self.inbox)
        other_path = self.workspace / "unavailable-project"; other_path.mkdir()
        other = Inbox(other_path); other.init("other-root")
        item = other.publish(spec(), "other-root")
        pending = other.submit(item["id"], 1, "Keep this pending", "offline-reply")
        unavailable_id = catalog.register(other)
        self.server.catalog = catalog
        moved_path = self.workspace / "moved-project"
        other_path.rename(moved_path)
        snapshot = json.load(self.request("/api/inbox"))
        self.assertEqual([entry["workspace_id"] for entry in snapshot["unavailable"]], [unavailable_id])
        self.assertNotIn("needs_you", snapshot["unavailable"][0])
        self.assertTrue(snapshot["unavailable"][0]["error"])
        self.assertEqual(catalog.resolve(healthy_id).workspace, self.workspace)
        viewed = json.load(self.request(f"/api/item?id={healthy['id']}&workspace={healthy_id}"))
        self.assertEqual(viewed["title"], healthy["title"])
        with self.assertRaises(Conflict): catalog.resolve_session(None)
        moved_path.rename(other_path)
        recovered = catalog.snapshot()
        self.assertEqual(recovered["unavailable"], [])
        self.assertIn(pending["id"], [receipt["id"] for receipt in recovered["pending"]])
        backup = other.db_path.with_suffix(".backup"); other.db_path.rename(backup)
        try:
            self.assertEqual(catalog.snapshot()["unavailable"][0]["workspace_id"], unavailable_id)
            self.assertEqual(catalog.resolve(healthy_id).get(healthy["id"])["id"], healthy["id"])
        finally:
            backup.rename(other.db_path)

    def test_http_structured_draft_submission_and_retained_question_definitions(self):
        item = self.publish(questions=questions())
        answers = {"ownership": {"option": 1}, "evidence": {"text": "Retain a bounded snapshot"}}
        draft = json.load(self.request("/api/draft", {"id": item["id"], "revision": 1, "body": "", "expected": 0, "answers": answers}))
        self.assertEqual(draft["answers"], answers)
        viewed = json.load(self.request(f"/api/item?id={item['id']}"))
        self.assertEqual(viewed["drafts"]["web"]["answers"], answers)
        receipt = json.load(self.request("/api/submit", {"id": item["id"], "revision": 1, "request_id": "http-options", "answers": answers}))
        self.assertEqual(receipt["answers"], answers)
        self.assertEqual(receipt["body"], "")
        viewed = json.load(self.request(f"/api/item?id={item['id']}"))
        self.assertEqual(viewed["drafts"]["web"]["answers"], {})
        self.assertEqual(viewed["submissions"][0]["questions"], questions())
        feed = json.load(self.request("/api/inbox"))["messages"]
        self.assertIn("Move it into the service", feed[0]["text"])
        self.assertIn("Retain a bounded snapshot", feed[0]["text"])


if __name__ == "__main__":
    # Explicit loading avoids inheriting the core test methods into HttpTests.
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(NetworkTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(InboxTests))
    suite.addTests(HttpTests(name) for name in dir(HttpTests) if name.startswith("test_http_"))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not outcome.wasSuccessful())
