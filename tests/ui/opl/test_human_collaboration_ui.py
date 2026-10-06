"""Real-browser review journeys. Requires Playwright and a local Chromium.

No browser/plugin dependency is installed implicitly and no AI calls are made.
Set OPL_CHROMIUM_BIN when Chromium is not discoverable on PATH.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/opl/skills/human-collaboration/scripts"))
from inbox import Inbox
from server import HumanServer
from service import connection_links

try:
    from playwright.sync_api import sync_playwright, expect, Error as PlaywrightError
except ImportError:
    raise SystemExit("UI gate blocked: install the development-only Python Playwright package in the test environment.")


class HumanUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        binary = os.environ.get("OPL_CHROMIUM_BIN") or shutil.which("chromium") or shutil.which("google-chrome")
        options = {"headless": True, "args": ["--no-sandbox"]}
        try:
            if binary:
                cls.browser = cls.playwright.chromium.launch(executable_path=binary, **options)
                return
            if os.name == "nt":
                for channel in ("chrome", "msedge"):
                    try:
                        cls.browser = cls.playwright.chromium.launch(channel=channel, **options)
                        return
                    except PlaywrightError as error:
                        if f"Chromium distribution '{channel}' is not found" not in str(error):
                            raise
            if Path(cls.playwright.chromium.executable_path).is_file():
                cls.browser = cls.playwright.chromium.launch(**options)
                return
            raise RuntimeError("UI gate blocked: install Chrome/Edge on Windows, run python -m playwright install chromium, or set OPL_CHROMIUM_BIN to an installed Chromium executable")
        except (PlaywrightError, RuntimeError):
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.playwright.stop()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        (self.workspace / "policy.py").write_text("retained_events = session.events\n", encoding="utf-8")
        (self.workspace / "flow.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="620" height="110"><rect width="620" height="110" fill="#18252a"/><text x="24" y="60" fill="white" font-size="20">Session evidence → Task-specific view → Prediction</text></svg>', encoding="utf-8")
        self.inbox = Inbox(self.workspace); self.inbox.init("root-test")
        self.item = self.inbox.publish({"title": "Keep evidence; bound inference", "summary": "Review the boundary between session storage and model context.", "why_now": "Prediction callers do not yet depend on the storage contract.", "priority": 10, "decision": True, "sources": ["flow.svg", "policy.py"], "brief": "## The decision\n\nRetain session evidence. Bound the **task-specific view**, not the underlying history.\n\n![Evidence flow](source:0)\n\n## Concrete case\n\nAfter reconnect, replaying missed notes can be worse than continuing coherently.\n\n## Challenge\n\nWhich responsibility belongs to storage, and which belongs to the scheduler?\n\n<script>window.unsafe = true</script>"}, "root-test")
        self.server = HumanServer(self.inbox, "127.0.0.1", 0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True); self.worker.start()
        self.addCleanup(self.close_server)
        self.context = self.browser.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", lambda message: self.errors.append(message.text) if message.type == "error" else None)
        self.url = connection_links("127.0.0.1", self.server.server_port, self.server.token, self.server.guid)["url"]
        self.requests = []
        self.page.on("request", lambda request: self.requests.append(request.url))
        self.page.goto(self.url)
        expect(self.page.get_by_role("button", name=self.item["title"], exact=True)).to_be_visible()

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join()

    def open_item(self):
        self.page.get_by_role("button", name=self.item["title"], exact=True).click()
        expect(self.page.locator("#reply")).to_be_visible()

    def assert_no_overflow(self):
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))

    def test_mobile_draft_refresh_submit_and_root_outcome(self):
        self.open_item()
        expect(self.page.get_by_role("img", name="Evidence flow")).to_be_visible()
        self.assertFalse(self.page.evaluate("Boolean(window.unsafe)"))
        self.page.locator("#reply").fill("#6 is conflating evidence retention and inference budget.")
        self.page.get_by_role("button", name="Save draft", exact=True).click()
        expect(self.page.locator("#draft-status")).to_contain_text("workspace")
        self.assertEqual(self.inbox.snapshot()["pending"], [])
        self.page.reload()
        expect(self.page.locator("#reply")).to_have_value("#6 is conflating evidence retention and inference budget.")
        from urllib.parse import parse_qs, urlsplit
        self.assertEqual(parse_qs(urlsplit(self.page.url).query)["guid"], [self.server.guid])
        for url in self.requests:
            parsed = urlsplit(url)
            if parsed.scheme == "http":
                self.assertEqual(parse_qs(parsed.query).get("guid"), [self.server.guid])
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator(".message.human")).to_contain_text("conflating")
        receipt = self.inbox.snapshot()["pending"][0]
        self.inbox.claim(receipt["id"], "root-test")
        self.inbox.outcome(receipt["id"], {"text": "Split the storage and inference-view contracts.", "disposition": "adopted", "source_review": "The fixture remained unchanged.", "references": ["policy.py"]}, "root-test")
        expect(self.page.locator(".conversation")).to_contain_text("Split the storage", timeout=8000)
        expect(self.page.locator(".detail-meta")).to_contain_text("resolved")
        self.assert_no_overflow(); self.assertEqual(self.errors, [])
        self.capture("mobile-outcome.png")

    def test_failed_response_retries_one_durable_submission(self):
        self.open_item()
        self.page.locator("#reply").fill("Keep the source evidence.")
        self.page.get_by_role("combobox", name="Reply type").select_option("question")
        def commit_then_disconnect(route):
            route.fetch(); route.abort()
        self.page.route("**/api/submit?*", commit_then_disconnect, times=1)
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator("#notice")).to_contain_text("retained for retry")
        self.page.reload()
        expect(self.page.locator("#reply")).to_have_value("Keep the source evidence.")
        expect(self.page.get_by_role("combobox", name="Reply type")).to_have_value("question")
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator("#reply")).to_have_value("")
        self.assertEqual(len(self.inbox.get(self.item["id"])["submissions"]), 1)
        self.assertEqual(self.inbox.get(self.item["id"])["submissions"][0]["kind"], "question")

    def test_older_revision_draft_can_be_reopened_and_submitted(self):
        self.inbox.revise(self.item["id"], {"title": "Newer framing", "summary": "A newer brief exists.",
                          "why_now": "The old framing needed clarification.", "brief": "Review the new framing."},
                          "Clarify framing", "root-test")
        self.inbox.save_draft(self.item["id"], 1, "My draft on the original brief", 0)
        self.page.reload()
        self.page.get_by_role("button", name="Newer framing", exact=True).click()
        selector = self.page.get_by_role("combobox", name="Brief revision")
        expect(selector).to_contain_text("Revision 1 · draft")
        selector.select_option("1")
        expect(self.page.locator("#reply")).to_have_value("My draft on the original brief")
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator(".message.human")).to_contain_text("original brief")
        receipt = self.inbox.snapshot()["pending"][0]
        self.assertEqual(receipt["revision"], 1)
        self.assert_no_overflow(); self.assertEqual(self.errors, [])

    def test_deferred_candidate_waits_for_root_preparation(self):
        candidate = self.inbox.publish({"title": "Needs more context", "summary": "An unprepared brief.",
                                       "why_now": "Its sources are not yet selected.", "brief": "Work in progress.",
                                       "state": "candidate"}, "root-test")
        self.inbox.move(candidate["id"], "later", "Prepare context first", thread="root-test")
        self.page.reload()
        self.page.get_by_role("button", name="Needs you", exact=True).click()
        self.page.get_by_text("Later (1)", exact=True).click()
        self.page.get_by_role("button", name="Needs more context", exact=True).click()
        expect(self.page.locator(".warning")).to_contain_text("not prepared")
        expect(self.page.locator("#reply")).to_have_count(0)
        expect(self.page.get_by_role("button", name="Start", exact=True)).to_have_count(0)
        expect(self.page.get_by_role("button", name="Return to queue", exact=True)).to_have_count(0)
        self.inbox.move(candidate["id"], "ready", "Context prepared", thread="root-test")
        self.page.get_by_role("button", name="Refresh", exact=True).click()
        expect(self.page.locator("#reply")).to_be_visible()
        expect(self.page.get_by_role("button", name="Start", exact=True)).to_be_visible()
        self.assert_no_overflow(); self.assertEqual(self.errors, [])

    def test_desktop_drift_snapshot_and_human_initiated_contribution(self):
        self.page.set_viewport_size({"width": 1280, "height": 900})
        (self.workspace / "policy.py").write_text("retained_events = []\n", encoding="utf-8")
        self.open_item()
        expect(self.page.locator(".warning")).to_contain_text("Context changed")
        source = self.page.locator(".source").filter(has_text="policy.py")
        source.get_by_role("button", name="Reviewed snapshot").click()
        expect(source.locator("pre")).to_contain_text("session.events")
        source.get_by_role("button", name="Current file").click()
        expect(source.locator("pre")).to_contain_text("= []")
        self.assert_no_overflow(); self.capture("desktop-review.png")
        self.page.get_by_role("button", name="Start a contribution").click()
        self.page.locator("#new-title").fill("Reconsider the recovery premise")
        self.page.locator("#new-body").fill("The scheduler should own the audible commitment.")
        self.page.get_by_role("button", name="Send contribution", exact=True).click()
        expect(self.page.locator(".conversation")).to_contain_text("audible commitment")
        self.assertEqual(len(self.inbox.snapshot()["pending"]), 1)
        self.assertEqual(self.errors, [])

    def test_combined_feed_filter_and_sessions_reorder_after_reply(self):
        self.inbox.init("root-second", title="Second session")
        self.inbox.init("root-empty", title="Quiet session")
        closed = self.inbox.publish({"title": "Completed discussion", "summary": "Completed work remains available.",
                                     "why_now": "Retain its outcome.", "brief": "An earlier discussion."}, "root-empty")
        done = self.inbox.submit(closed["id"], 1, "Completed feedback", "done-feedback")
        self.inbox.claim(done["id"], "root-empty")
        self.inbox.outcome(done["id"], {"disposition": "adopted", "text": "Completed the discussion.",
                                      "source_review": "Synthetic UI fixture, not a code change.", "references": []}, "root-empty")
        self.inbox.init("root-no-items", title="Empty session")
        newer = self.inbox.publish({"title": "A newer question", "summary": "New activity should appear without Refresh.",
                                    "why_now": "Another session needs input.", "priority": 0,
                                    "brief": "How should we split ownership?"}, "root-second")
        # Auto-refresh is the consumer under test, not an explicit browser reload.
        expect(self.page.locator("#items button").first).to_have_text("A newer question", timeout=8000)
        sessions = self.inbox.snapshot()["sessions"]
        second = next(session for session in sessions if session["thread"] == "root-second")
        first = next(session for session in sessions if session["thread"] == "root-test")
        quiet = next(session for session in sessions if session["thread"] == "root-empty")
        rows = self.page.locator("#sessions [data-session]")
        expect(rows.first).to_have_attribute("data-session", second["id"])
        expect(rows.last).to_have_attribute("data-session", quiet["id"])
        expect(rows.last).to_contain_text("No pending questions")
        expect(self.page.locator("#sessions")).not_to_contain_text("Empty session")
        self.page.locator("#sessions [data-session]").filter(has_text="Second session").click()
        expect(self.page.get_by_role("button", name=self.item["title"], exact=True)).to_have_count(0)
        expect(self.page.get_by_role("button", name=newer["title"], exact=True)).to_be_visible()
        self.page.locator(f'#sessions [data-session="{first["id"]}"]').click()
        self.open_item()
        self.page.locator("#reply").fill("A draft must survive background updates.")
        extra = self.inbox.publish({"title": "Another message while typing", "summary": "Typing remains uninterrupted.",
                                    "why_now": "A parallel session is working.", "brief": "New information."}, "root-second")
        expect(self.page.locator("#reply")).to_have_value("A draft must survive background updates.")
        # Wait for the server-side update to reach this filtered sidebar.
        expect(self.page.locator(f'#sessions [data-session="{second["id"]}"]')).to_contain_text("2 need you", timeout=8000)
        expect(self.page.locator("#reply")).to_be_focused()
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator(".message.human")).to_contain_text("survive background")
        expect(self.page.locator(f'#sessions [data-session="{first["id"]}"]')).to_contain_text("No pending questions")
        expect(self.page.locator(f'#sessions [data-session="{first["id"]}"]')).to_contain_text("1 with agent")
        self.assertEqual(self.inbox.snapshot("root-second")["pending"], [])
        self.page.get_by_role("button", name="Back to inbox", exact=True).click()
        self.page.get_by_role("button", name="All sessions", exact=False).click()
        expect(self.page.locator("#items button").first).to_have_text(self.item["title"])
        self.assert_no_overflow(); self.assertEqual(self.errors, [])
        self.capture("mobile-combined-sessions.png")

    def test_cross_workspace_same_item_id_routes_draft_and_reply(self):
        other_path = self.workspace / "other-project"; other_path.mkdir()
        other = Inbox(other_path); other.init("other-root", title="Other project session")
        item = other.publish({"title": "Same number, different project", "summary": "This contribution has its own workspace.",
                              "why_now": "Replies must keep their project identity.", "brief": "Review the other project."}, "other-root")
        self.assertEqual(item["id"], self.item["id"])
        self.server.catalog.register(other)
        expect(self.page.get_by_role("button", name=item["title"], exact=True)).to_be_visible(timeout=8000)
        self.page.get_by_role("button", name=item["title"], exact=True).click()
        self.page.locator("#reply").fill("Only the other project should receive this.")
        self.page.get_by_role("button", name="Save draft", exact=True).click()
        expect(self.page.locator("#draft-status")).to_contain_text("workspace")
        self.page.reload()
        expect(self.page.locator("#reply")).to_have_value("Only the other project should receive this.")
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator(".message.human")).to_contain_text("other project")
        self.assertEqual(self.inbox.snapshot()["pending"], [])
        self.assertEqual(len(other.snapshot()["pending"]), 1)
        self.assert_no_overflow(); self.assertEqual(self.errors, [])
        self.page.set_viewport_size({"width": 1280, "height": 900})
        self.page.get_by_role("button", name="Back to inbox", exact=True).click()
        self.page.get_by_role("button", name="Start a contribution", exact=True).click()
        self.page.locator("#new-title").fill("A contribution without a selected recipient")
        self.page.locator("#new-body").fill("Choose the right session before sending.")
        self.page.get_by_role("button", name="Send contribution", exact=True).click()
        expect(self.page.locator("#notice")).to_contain_text("Choose the session")
        target = next(session for session in other.snapshot()["sessions"])
        self.page.locator("#contribution-session").select_option(target["id"])
        self.page.locator("#new-title").fill("Explicitly for the other session")
        self.page.locator("#new-body").fill("Route this to the selected recipient.")
        self.page.get_by_role("button", name="Send contribution", exact=True).click()
        expect(self.page.locator(".conversation")).to_contain_text("selected recipient")
        self.assertEqual(self.inbox.snapshot()["pending"], [])
        self.assertEqual(len(other.snapshot()["pending"]), 2)
        self.assert_no_overflow(); self.assertEqual(self.errors, [])
        self.capture("desktop-cross-workspace.png")
        other.db_path.rename(other.root / "retained.sqlite3")
        self.page.get_by_role("button", name="Back to inbox", exact=True).click()
        expect(self.page.locator("#sessions [data-session]")).to_have_count(1, timeout=8000)
        expect(self.page.locator("#sessions")).not_to_contain_text("Other project session")
        self.open_item()
        expect(self.page.locator("#reply")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_structured_questions_drafts_assumptions_and_human_correction(self):
        questions = [{"id": "approach", "prompt": "Which approach should the agent start?",
                      "options": ["Use the existing module", "Split the module", "Run an experiment"]},
                     {"id": "check", "prompt": "Which case should be checked first?",
                      "options": ["The common case", "A recovery case", "A boundary case"]}]
        item = self.inbox.publish({"title": "Two optional questions", "summary": "Answer one or both; ongoing work continues.",
                                   "why_now": "The next independent step is nearly ready.", "brief": "## Context\n\nA Markdown brief comes before the optional question blocks.",
                                   "questions": questions}, "root-test")
        expect(self.page.get_by_role("button", name=item["title"], exact=True)).to_be_visible(timeout=8000)
        self.page.get_by_role("button", name=item["title"], exact=True).click()
        expect(self.page.get_by_role("radio")).to_have_count(8)
        self.page.get_by_role("radio", name="Split the module", exact=True).check()
        self.page.get_by_role("textbox", name="Your own answer: Which case should be checked first?").fill("Check the cancellation path.")
        self.page.get_by_role("button", name="Save draft", exact=True).click()
        expect(self.page.locator("#draft-status")).to_contain_text("workspace")
        self.page.reload()
        expect(self.page.get_by_role("radio", name="Split the module", exact=True)).to_be_checked()
        expect(self.page.get_by_role("textbox", name="Your own answer: Which case should be checked first?")).to_have_value("Check the cancellation path.")
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator(".message.human")).to_contain_text("Split the module")
        expect(self.page.locator(".message.human")).to_contain_text("cancellation path")
        receipt = self.inbox.get(item["id"])["submissions"][0]
        self.inbox.claim(receipt["id"], "root-test")
        self.inbox.outcome(receipt["id"], {"disposition": "adopted", "text": "Used the selected approach.",
                                         "source_review": "Synthetic UI fixture.", "references": []}, "root-test")
        assumed = self.inbox.publish({"title": "Nonblocking recommendation", "summary": "A reversible next step.",
                                      "why_now": "No independent work remains.", "brief": "The recommendation can be corrected later.",
                                      "questions": [questions[0]]}, "root-test")
        self.page.get_by_role("button", name="Back to inbox", exact=True).click()
        expect(self.page.locator("#items .feed-message").first).to_contain_text("Nonblocking recommendation", timeout=8000)
        self.page.locator("#items .feed-message").first.get_by_role("button").click()
        self.page.locator("#reply").fill("Keep my draft while the agent moves forward.")
        self.page.locator("#reply").evaluate("node => { node.focus(); node.setSelectionRange(3, 10) }")
        self.inbox.assume(assumed["id"], ["approach"], "No independent work remains; the next step is authorized and reversible.", "root-test")
        expect(self.page.locator("#items .feed-message").first).to_contain_text("answer assumed", timeout=8000)
        expect(self.page.locator(".question .warning")).to_contain_text("Answer assumed: Use the existing module", timeout=8000)
        expect(self.page.locator("#reply")).to_have_value("Keep my draft while the agent moves forward.")
        expect(self.page.locator("#reply")).to_be_focused()
        self.assertEqual(self.page.locator("#reply").evaluate("node => [node.selectionStart, node.selectionEnd]"), [3, 10])
        self.page.get_by_role("radio", name="Run an experiment", exact=True).check()
        self.page.get_by_role("button", name="Send", exact=True).click()
        expect(self.page.locator(".message.human")).to_contain_text("Run an experiment")
        self.assert_no_overflow(); self.assertEqual(self.errors, [])
        self.capture("mobile-questions-and-assumption.png")

    def capture(self, name):
        directory = os.environ.get("OPL_UI_EVIDENCE")
        if directory:
            path = Path(directory); path.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(path / name), full_page=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
