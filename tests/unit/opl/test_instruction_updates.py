import importlib.util
import hashlib
import re
from pathlib import Path
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
        (self.plugin / "AGENTS.md").write_bytes(content(3, "Installed OPL defaults."))
        self.target = self.home / "AGENTS.md"

    def apply(self, expected):
        bundled = (self.plugin / "AGENTS.md").read_bytes()
        return instructions.apply_installed(self.home, self.plugin, expected, str(self.target),
                                            hashlib.sha256(bundled).hexdigest())

    def test_versions_and_override(self):
        for data, state in [(content(3), "current"), (content(1), "update"), (content(4), "newer"),
                            (b"Personal", "setup"), (content(1) + content(2), "invalid")]:
            self.target.write_bytes(data)
            self.assertEqual(instructions.snapshot(self.home, self.plugin)["status"], state)
        override = self.home / "AGENTS.override.md"
        override.write_bytes(content(3))
        self.assertEqual(instructions.snapshot(self.home, self.plugin)["target"], str(override))
        override.write_bytes(b"")
        self.assertEqual(instructions.effective_target(self.home), self.target)

    def test_backup_is_exact_and_same_content_is_noop(self):
        original = b"\xef\xbb\xbf" + content(1).replace(b"\n", b"\r\n")
        self.target.write_bytes(original)
        result = self.apply(hashlib.sha256(original).hexdigest())
        self.assertEqual(Path(result["backup"]).read_bytes(), original)
        self.assertRegex(Path(result["backup"]).name, r"^AGENTS\.md\.opl-backup-\d{8}-001$")
        self.assertEqual(self.target.read_bytes(), (self.plugin / "AGENTS.md").read_bytes())
        again = self.apply(result["sha256"])
        self.assertFalse(again["changed"])

    def test_dated_backup_sequence_never_overwrites_existing_backup(self):
        original = content(1, "First version")
        self.target.write_bytes(original)
        first = self.apply(hashlib.sha256(original).hexdigest())
        first_backup = Path(first["backup"])
        self.assertTrue(re.fullmatch(r"AGENTS\.md\.opl-backup-\d{8}-001", first_backup.name))

        second_original = self.target.read_bytes()
        (self.plugin / "AGENTS.md").write_bytes(content(4, "Second installed version."))
        second = self.apply(hashlib.sha256(second_original).hexdigest())
        second_backup = Path(second["backup"])
        self.assertEqual(second_backup.name, first_backup.name[:-3] + "002")
        self.assertEqual(first_backup.read_bytes(), original)
        self.assertEqual(second_backup.read_bytes(), second_original)

    def test_concurrent_edit_and_downgrade_rejected(self):
        self.target.write_bytes(content(1))
        with self.assertRaisesRegex(ValueError, "changed after inspection"):
            self.apply("old hash")
        self.target.write_bytes(content(4))
        with self.assertRaisesRegex(ValueError, "downgrade"):
            self.apply(hashlib.sha256(content(4)).hexdigest())

    def test_missing_target_is_created_without_backup(self):
        result = self.apply("missing")
        self.assertIsNone(result["backup"])
        self.assertEqual(self.target.read_bytes(), (self.plugin / "AGENTS.md").read_bytes())

    def test_changed_override_during_apply_is_rejected(self):
        original = content(1)
        self.target.write_bytes(original)
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
                self.apply(hashlib.sha256(original).hexdigest())
        self.assertEqual(self.target.read_bytes(), original)

    def test_failed_atomic_replace_preserves_original(self):
        original = content(1)
        self.target.write_bytes(original)
        with patch.object(instructions.os, "replace", side_effect=OSError("locked")):
            with self.assertRaisesRegex(OSError, "locked"):
                self.apply(hashlib.sha256(original).hexdigest())
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(list(self.home.glob(".opl-instructions-*")), [])

    def test_changed_installed_instructions_after_inspection_are_rejected(self):
        original = content(1)
        self.target.write_bytes(original)
        inspected = instructions.snapshot(self.home, self.plugin)
        (self.plugin / "AGENTS.md").write_bytes(content(3, "Changed installed defaults."))
        with self.assertRaisesRegex(ValueError, "changed after inspection"):
            instructions.apply_installed(self.home, self.plugin, inspected["sha256"], inspected["target"],
                                         inspected["bundled_sha256"])
        self.assertEqual(self.target.read_bytes(), original)

    def test_changed_installed_instructions_during_apply_are_rejected(self):
        original = content(1)
        self.target.write_bytes(original)
        real_snapshot = instructions.snapshot
        calls = 0

        def changed(home, root):
            nonlocal calls
            calls += 1
            if calls == 2:
                (root / "AGENTS.md").write_bytes(content(3, "Changed installed defaults."))
            return real_snapshot(home, root)

        with patch.object(instructions, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "during application"):
                self.apply(hashlib.sha256(original).hexdigest())
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(list(self.home.glob(".opl-instructions-*")), [])


if __name__ == "__main__":
    unittest.main()
