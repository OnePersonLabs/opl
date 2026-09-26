"""Focused behavior checks for the advisory technical prose linter."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[3] / "plugins/opl/skills/simplified-technical-english/scripts/ste_lint.py"
SPEC = importlib.util.spec_from_file_location("ste_lint", SCRIPT)
assert SPEC and SPEC.loader
LINTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINTER)


class SteLintTests(unittest.TestCase):
    def test_reports_prose_but_skips_code_and_quotes(self):
        text = (
            "# Heading\n\n"
            "- The service MUST retain each original condition and must show a clear error when a request has an invalid token because users need to know which exact input failed.\n"
            "- The service can't leverage magic.\n\n"
            "> A quoted statement can't be changed.\n\n"
            "```text\nThis robust code can't be linted.\n```\n"
            "A `robust` value remains literal.\n"
        )
        findings = LINTER.lint(text, "normative")
        self.assertIn("long-sentence", [item[1] for item in findings])
        self.assertEqual([item[1] for item in findings].count("contraction"), 1)
        self.assertEqual([item[1] for item in findings].count("empty-word"), 1)
        self.assertEqual({item[0] for item in findings}, {3, 4})

    def test_guidance_has_lighter_sentence_limit(self):
        prose = "The service " + "reads one input " * 8 + "and returns one result."
        self.assertTrue(any(item[1] == "long-sentence" for item in LINTER.lint(prose, "normative")))
        self.assertFalse(any(item[1] == "long-sentence" for item in LINTER.lint(prose, "guidance")))

    def test_cli_is_advisory_and_reports_read_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spec.md"
            original = "The system can't leverage this.\n"
            path.write_text(original, encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--mode", "normative", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn("contraction", result.stdout)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            missing = subprocess.run([sys.executable, str(SCRIPT), "--mode", "guidance", str(path.with_name("missing.md"))], capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("cannot read", missing.stderr)


if __name__ == "__main__":
    unittest.main()
