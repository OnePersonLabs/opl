"""Focused behavior checks for the de-AI prose scanner."""

import importlib.util
import io
from datetime import date, timedelta
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[3] / "plugins/opl/skills/de-ai-writing/scripts/check_ai_signs.py"
SPEC = importlib.util.spec_from_file_location("check_ai_signs", SCRIPT)
assert SPEC and SPEC.loader
SCANNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCANNER
SPEC.loader.exec_module(SCANNER)
SKILL = SCRIPT.parents[1] / "SKILL.md"
SIGNS = SCRIPT.parents[1] / "references/signs.md"


class ScannerTests(unittest.TestCase):
    def test_finds_unneeded_contrast_significance_and_honest_style_cues(self):
        text = (
            "It's this, not that.\n"
            "Here's why it matters.\n"
            "Use the detail that matters.\n"
            "An honest uncertainty can make the answer feel more personal.\n"
        )
        findings = SCANNER.scan_text(text, "sample.txt", ".txt")
        identifiers = {item.rule_id for item in findings}
        self.assertEqual(identifiers, {"2.4", "2.5", "2.8"})

    def test_finds_lexical_structural_and_density_signs(self):
        text = (
            "# Powerful Tools For Modern Teams\n\n"
            "- **Speed:** It serves as a crucial, robust tapestry, highlighting its pivotal role.\n"
            "- **Scale:** Great question -- let me know if this helps.\n"
            "- **Trust:** It is not just software, but a vibrant platform.\n"
            "The **first point**, **second point**, and **third point** all receive emphasis.\n"
        )
        findings = SCANNER.scan_text(text, "sample.md", ".md")
        identifiers = {item.rule_id for item in findings}
        self.assertTrue({"1.1", "1.3", "2.1", "2.2", "2.4", "3.1", "3.2", "3.3", "4.1"}.issubset(identifiers))

    def test_skips_code_quotes_frontmatter_and_html_exclusions(self):
        markdown = (
            "---\ntitle: Great Question For Every Reader\n---\n"
            "> Great question. This serves as a testament.\n"
            "```text\nGreat question. This serves as a testament.\n```\n"
            "A source said, \"This serves as a testament.\"\n"
            "Use `it serves as a testament` as the search string.\n"
            "The station has six platforms.\n"
        )
        self.assertEqual(SCANNER.scan_text(markdown, "clean.md", ".md"), [])
        html = "<script>Great question</script><blockquote>It serves as a testament.</blockquote><p>The station has six platforms.</p>"
        self.assertEqual(SCANNER.scan_text(html, "clean.html", ".html"), [])

    def test_reports_repeated_breaks_but_not_frontmatter(self):
        text = "---\ntitle: Plain title\n---\n\nFirst.\n\n---\n\nSecond.\n\n---\n\nThird.\n"
        findings = SCANNER.scan_text(text, "breaks.md", ".md")
        self.assertEqual([item.rule_id for item in findings], ["3.8", "3.8"])

    def test_cli_scans_directories_stdin_and_summarizes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.md").write_text("Great question.\n", encoding="utf-8")
            (root / "two.txt").write_text("In conclusion, this may vary.\n", encoding="utf-8")
            (root / "skip.py").write_text("Great question.\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(root), "-", "--summary"],
                input="Experts argue that it is crucial.\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("[4.1 chat residue]", result.stdout)
            self.assertIn("[1.5 vague attribution]", result.stdout)
            self.assertIn("RULE 5.1 didactic disclaimer: 1", result.stdout)
            self.assertNotIn("skip.py", result.stdout)

    def test_cli_errors_for_missing_and_unsupported_inputs(self):
        missing = subprocess.run([sys.executable, str(SCRIPT), "missing.md"], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("path does not exist", missing.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.py"
            path.write_text("Great question.\n", encoding="utf-8")
            unsupported = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)
            self.assertEqual(unsupported.returncode, 2)
            self.assertIn("unsupported file type", unsupported.stderr)

    def test_source_status_exit_codes(self):
        with patch.object(SCANNER, "latest_source", return_value=(SCANNER.SOURCE_REVISION, SCANNER.SOURCE_TIMESTAMP)):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(SCANNER.source_status(force=True), 0)
                self.assertIn("status: current", output.getvalue())
        with patch.object(SCANNER, "latest_source", return_value=(SCANNER.SOURCE_REVISION + 1, "later")):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(SCANNER.source_status(force=True), 1)
                self.assertIn("status: stale", output.getvalue())

    def test_source_status_skips_network_until_thirty_days_have_passed(self):
        with patch.object(SCANNER, "latest_source") as latest:
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                result = SCANNER.source_status(today=SCANNER.SOURCE_REVIEWED + timedelta(days=29))
            self.assertEqual(result, 0)
            self.assertIn("status: not due until", output.getvalue())
            latest.assert_not_called()
        with patch.object(SCANNER, "latest_source", return_value=(SCANNER.SOURCE_REVISION, SCANNER.SOURCE_TIMESTAMP)) as latest:
            with patch("sys.stdout", new_callable=io.StringIO):
                SCANNER.source_status(today=SCANNER.SOURCE_REVIEWED + timedelta(days=30))
            latest.assert_called_once()

    def test_source_metadata_stays_synchronized(self):
        skill = SKILL.read_text(encoding="utf-8")
        signs = SIGNS.read_text(encoding="utf-8")
        skill_date = re.search(r"Last source review: `([0-9]{4}-[0-9]{2}-[0-9]{2})`", skill)
        signs_date = re.search(r"Last reviewed: `([0-9]{4}-[0-9]{2}-[0-9]{2})`", signs)
        signs_revision = re.search(r"Source revision: `([0-9]+)`", signs)
        self.assertIsNotNone(skill_date)
        self.assertIsNotNone(signs_date)
        self.assertIsNotNone(signs_revision)
        self.assertEqual(skill_date.group(1), SCANNER.SOURCE_REVIEWED.isoformat())
        self.assertEqual(signs_date.group(1), SCANNER.SOURCE_REVIEWED.isoformat())
        self.assertEqual(int(signs_revision.group(1)), SCANNER.SOURCE_REVISION)


if __name__ == "__main__":
    unittest.main()
