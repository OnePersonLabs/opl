import importlib.util
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("instructions", ROOT / "plugins/opl/skills/update-instructions/scripts/instructions.py")
instructions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(instructions)


def content(number, text="Use my browser."):
    return f"<!-- opl-instructions-version: {number} -->\n\n{text}\n".encode()


class InstructionUpdates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="OPL é ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.plugin = self.root / "plugin"
        self.home.mkdir()
        self.plugin.mkdir()
        (self.plugin / "AGENTS.md").write_bytes(content(3))
        self.target = self.home / "AGENTS.md"
        self.candidate = self.root / "candidate.md"
        self.candidate.write_bytes(content(3, "Keep my CLI and deleted rule deleted."))

    def apply(self, expected):
        return instructions.apply_candidate(self.home, self.plugin, self.candidate, expected,
                                            str(self.target), hashlib.sha256(content(3)).hexdigest())

    def test_versions_and_override(self):
        for data, state in [(content(3), "current"), (content(1), "update"), (content(4), "newer"), (b"Personal", "setup"), (content(1) + content(2), "invalid")]:
            self.target.write_bytes(data)
            self.assertEqual(instructions.snapshot(self.home, self.plugin)["status"], state)
        override = self.home / "AGENTS.override.md"
        override.write_bytes(content(3))
        self.assertEqual(instructions.snapshot(self.home, self.plugin)["target"], str(override))
        override.write_bytes(b"")
        self.assertEqual(instructions.effective_target(self.home), self.target)

    def test_backup_is_exact_and_repeated_apply_is_noop(self):
        original = b"\xef\xbb\xbf" + content(1).replace(b"\n", b"\r\n")
        self.target.write_bytes(original)
        result = self.apply(hashlib.sha256(original).hexdigest())
        self.assertEqual(Path(result["backup"]).read_bytes(), original)
        self.assertEqual(self.target.read_bytes(), self.candidate.read_bytes())
        again = self.apply(result["sha256"])
        self.assertFalse(again["changed"])

    def test_concurrent_edit_and_downgrade_rejected(self):
        self.target.write_bytes(content(1))
        with self.assertRaisesRegex(ValueError, "changed since review"):
            self.apply("old hash")
        self.target.write_bytes(content(4))
        with self.assertRaisesRegex(ValueError, "downgrade"):
            self.apply(hashlib.sha256(content(4)).hexdigest())

    def test_missing_target_and_wrong_candidate_version(self):
        self.candidate.write_bytes(content(2))
        with self.assertRaisesRegex(ValueError, "installed"):
            self.apply("missing")
        self.candidate.write_bytes(content(3))
        result = self.apply("missing")
        self.assertIsNone(result["backup"])
        self.assertEqual(self.target.read_bytes(), content(3))

    def test_changed_override_during_apply_is_rejected(self):
        self.target.write_bytes(content(1))
        real_snapshot = instructions.snapshot
        calls = 0
        def changed(home, root):
            nonlocal calls
            calls += 1
            if calls == 2:
                (home / "AGENTS.override.md").write_bytes(content(2))
            return real_snapshot(home, root)
        with patch.object(instructions, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "during application"):
                self.apply(hashlib.sha256(content(1)).hexdigest())
        self.assertEqual(self.target.read_bytes(), content(1))

    def test_failed_atomic_replace_preserves_original(self):
        self.target.write_bytes(content(1))
        with patch.object(instructions.os, "replace", side_effect=OSError("locked")):
            with self.assertRaisesRegex(OSError, "locked"):
                self.apply(hashlib.sha256(content(1)).hexdigest())
        self.assertEqual(self.target.read_bytes(), content(1))
        self.assertEqual(list(self.home.glob(".opl-instructions-*")), [])

    def test_same_bytes_override_after_review_is_rejected(self):
        original = content(1)
        self.target.write_bytes(original)
        reviewed = instructions.snapshot(self.home, self.plugin)
        override = self.home / "AGENTS.override.md"
        override.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "changed since review"):
            instructions.apply_candidate(self.home, self.plugin, self.candidate, reviewed["sha256"],
                                         reviewed["target"], reviewed["bundled_sha256"])
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(override.read_bytes(), original)
        self.assertEqual(list(self.home.glob("*.opl-backup-*")), [])

    def test_changed_baseline_with_same_version_after_review_is_rejected(self):
        original = content(1)
        self.target.write_bytes(original)
        reviewed = instructions.snapshot(self.home, self.plugin)
        (self.plugin / "AGENTS.md").write_bytes(content(3, "Changed upstream behavior"))
        with self.assertRaisesRegex(ValueError, "changed since review"):
            instructions.apply_candidate(self.home, self.plugin, self.candidate, reviewed["sha256"],
                                         reviewed["target"], reviewed["bundled_sha256"])
        self.assertEqual(self.target.read_bytes(), original)

    def test_changed_baseline_during_application_is_rejected(self):
        self.target.write_bytes(content(1))
        real_snapshot = instructions.snapshot
        calls = 0
        def changed(home, root):
            nonlocal calls
            calls += 1
            if calls == 2:
                (root / "AGENTS.md").write_bytes(content(3, "Changed upstream behavior"))
            return real_snapshot(home, root)
        with patch.object(instructions, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "during application"):
                self.apply(hashlib.sha256(content(1)).hexdigest())
        self.assertEqual(self.target.read_bytes(), content(1))
        self.assertEqual(list(self.home.glob(".opl-instructions-*")), [])

    def test_history_skips_versions_and_detects_reuse(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        git("init")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        source = repo / instructions.SOURCE
        source.parent.mkdir(parents=True)
        def commit(data):
            source.write_bytes(data)
            git("add", ".")
            git("commit", "-m", "baseline")
        commit(content(1))
        commit(content(3))
        self.assertEqual(instructions.historical(repo, 1)[0], content(1))
        self.assertIsNone(instructions.historical(repo, 2))
        commit(content(1))
        self.assertEqual(len(instructions.historical(repo, 1)[1]), 2)
        output = self.root / "previous.md"
        instructions.baseline(1, output, repo)
        self.assertEqual(output.read_bytes(), content(1))
        with self.assertRaises(FileExistsError):
            instructions.baseline(1, output, repo)
        commit(content(1, "Different behavior"))
        with self.assertRaisesRegex(ValueError, "different historical"):
            instructions.historical(repo, 1)

    def test_unavailable_remote_surfaces_error(self):
        result = subprocess.CompletedProcess([], 1, b"", b"authentication failed")
        for wanted, upstream in [(9, instructions.LEGACY_UPSTREAM), (10, instructions.UPSTREAM), (11, instructions.UPSTREAM)]:
            with self.subTest(wanted=wanted), patch.object(instructions.subprocess, "run", return_value=result) as run:
                with self.assertRaisesRegex(RuntimeError, "retrieval failed"):
                    instructions.baseline(wanted, self.root / "baseline.md", None)
                self.assertEqual(run.call_args.args[0][4], upstream)

    def test_remote_history_routes_at_extraction_boundary(self):
        execute = subprocess.run
        for wanted, upstream in [(9, instructions.LEGACY_UPSTREAM), (10, instructions.UPSTREAM), (11, instructions.UPSTREAM)]:
            with self.subTest(wanted=wanted):
                repo = self.root / f"history-{wanted}"
                repo.mkdir()
                def git(*args):
                    execute(["git", "-C", str(repo), *args], check=True, capture_output=True)
                git("init", "-b", "main")
                git("config", "user.email", "test@example.invalid")
                git("config", "user.name", "Test")
                source = repo / instructions.SOURCE
                source.parent.mkdir(parents=True)
                source.write_bytes(content(wanted))
                git("add", ".")
                git("commit", "-m", "historical baseline")
                calls = []
                def routed_run(args, **kwargs):
                    if args[:2] == ["git", "clone"]:
                        calls.append(args[4])
                        args = [*args[:4], str(repo), *args[5:]]
                    return execute(args, **kwargs)
                output = self.root / f"baseline-{wanted}.md"
                with patch.object(instructions.subprocess, "run", side_effect=routed_run):
                    receipt = instructions.baseline(wanted, output, None)
                self.assertEqual(calls, [upstream])
                self.assertEqual(receipt["source"], upstream)
                self.assertEqual(output.read_bytes(), content(wanted))

    def test_merged_side_branch_version_collision_is_detected(self):
        repo = self.root / "merged-repo"
        repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout
        git("init", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        source = repo / instructions.SOURCE
        source.parent.mkdir(parents=True)
        def commit(data):
            source.write_bytes(data)
            git("add", ".")
            git("commit", "-m", "baseline")
        commit(b"Unversioned baseline\n")
        git("checkout", "-b", "side")
        commit(content(1, "Conflicting side behavior"))
        git("checkout", "main")
        commit(content(1))
        git("merge", "-s", "ours", "side", "-m", "merge")
        git("branch", "-D", "side")
        with self.assertRaisesRegex(ValueError, "different historical"):
            instructions.historical(repo, 1)


if __name__ == "__main__":
    unittest.main()
