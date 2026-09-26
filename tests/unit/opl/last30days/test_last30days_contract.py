from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = REPOSITORY_ROOT / "plugins" / "opl" / "skills" / "last30days"
SCRIPT = SKILL_ROOT / "scripts" / "last30days.py"
PYTHON_COMMAND = [sys.executable, "-B", "-X", "utf8"]


class Last30DaysNamespaceContractTest(unittest.TestCase):
    def test_skill_package_uses_last30days_identity(self) -> None:
        self.assertEqual(SKILL_ROOT.name, "last30days")
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: last30days\n", skill_text)
        self.assertTrue(SCRIPT.is_file())

    def test_skill_uses_host_neutral_web_wording(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        planning_text = (SKILL_ROOT / "references" / "search-planning.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("search the web for", skill_text)
        self.assertIn("Get-Command", skill_text)
        self.assertIn("command -v", skill_text)
        self.assertIn("& $env:LAST30DAYS_PYTHON -B -X utf8", skill_text)
        self.assertIn('"$LAST30DAYS_PYTHON" -B -X utf8', skill_text)
        self.assertNotIn("AskUserQuestion", skill_text)
        self.assertNotIn("WebSearch", skill_text)
        self.assertIn("Doctor labels the", planning_text)
        self.assertIn("source as `web`; map that label explicitly", planning_text)
        self.assertNotIn("doctor/diagnose", planning_text)

    def test_runtime_defaults_use_last30days_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            command = [
                *PYTHON_COMMAND,
                "-c",
                (
                    "import json, sys; "
                    f"sys.path.insert(0, {str((SKILL_ROOT / 'scripts')).__repr__()}); "
                    "from lib import env; "
                    "print(json.dumps({"
                    "'config_dir': str(env.CONFIG_DIR), "
                    "'project_env': str(env._find_project_env() or ''), "
                    "'keychain_prefix': env.KEYCHAIN_SERVICE_PREFIX, "
                    "'pass_prefix': env.DEFAULT_PASS_PATH_PREFIX"
                    "}))"
                ),
            ]
            process_env = os.environ.copy()
            process_env["HOME"] = temp_home
            process_env["USERPROFILE"] = temp_home
            process_env.pop("LAST30DAYS_CONFIG_DIR", None)
            result = subprocess.run(
                command,
                cwd=temp_home,
                env=process_env,
                check=True,
                capture_output=True,
                encoding="utf-8",
            )
            payload = json.loads(result.stdout)

        self.assertEqual(
            payload["config_dir"],
            str(Path(temp_home) / ".config" / "last30days"),
        )
        self.assertEqual(payload["keychain_prefix"], "last30days-")
        self.assertEqual(payload["pass_prefix"], "last30days/")

    def test_project_config_uses_agents_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            nested = project / "src"
            project_env = project / ".agents" / "last30days.env"
            project_env.parent.mkdir(parents=True)
            project_env.write_text("LAST30DAYS_DEFAULT_SEARCH=reddit\n", encoding="utf-8")
            (project / ".git").mkdir()
            nested.mkdir()

            command = [
                *PYTHON_COMMAND,
                "-c",
                (
                    "import json, sys; "
                    f"sys.path.insert(0, {str((SKILL_ROOT / 'scripts')).__repr__()}); "
                    "from lib import env; "
                    "config = env.get_config(); "
                    "print(json.dumps({"
                    "'source': config.get('_CONFIG_SOURCE'), "
                    "'default_search': config.get('LAST30DAYS_DEFAULT_SEARCH')"
                    "}))"
                ),
            ]
            process_env = os.environ.copy()
            process_env["HOME"] = str(Path(temp_dir) / "home")
            process_env["USERPROFILE"] = str(Path(temp_dir) / "home")
            process_env["LAST30DAYS_CONFIG_DIR"] = ""
            process_env["LAST30DAYS_TRUST_PROJECT_CONFIG"] = "1"
            result = subprocess.run(
                command,
                cwd=nested,
                env=process_env,
                check=True,
                capture_output=True,
                encoding="utf-8",
            )
            payload = json.loads(result.stdout)

        self.assertEqual(payload["source"], f"project:{project_env}")
        self.assertEqual(payload["default_search"], "reddit")

    def test_cli_help_uses_last30days_command_name(self) -> None:
        result = subprocess.run(
            [*PYTHON_COMMAND, str(SCRIPT), "--help"],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )
        self.assertIn("last30days", result.stdout)

    def test_version_resolution_is_anchored_to_nearest_codex_plugin_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_root = Path(temp_dir) / "unexpected" / "layout" / "plugin-root"
            manifest = plugin_root / ".codex-plugin" / "plugin.json"
            script_path = plugin_root / "skills" / "last30days" / "scripts" / "tool.py"
            manifest.parent.mkdir(parents=True)
            script_path.parent.mkdir(parents=True)
            manifest.write_text('{"name":"plugin","version":"9.8.7"}\n', encoding="utf-8")

            command = [
                *PYTHON_COMMAND,
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {str((SKILL_ROOT / 'scripts')).__repr__()}); "
                    "from lib.skill_meta import read_plugin_version; "
                    f"print(read_plugin_version({str(script_path).__repr__()}) or '')"
                ),
            ]
            result = subprocess.run(command, check=True, capture_output=True, encoding="utf-8")

        self.assertEqual(result.stdout.strip(), "9.8.7")

    def test_doctor_cache_is_explicit_cached_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            process_env = {
                "PATH": os.environ.get("PATH", ""),
                "USER": os.environ.get("USER", ""),
                "HOME": temp_dir,
                "USERPROFILE": temp_dir,
                "LAST30DAYS_CONFIG_DIR": temp_dir,
                "BRAVE_API_KEY": "doctor-must-not-print-this-secret",
            }
            live = subprocess.run(
                [*PYTHON_COMMAND, str(SCRIPT), "doctor", "--json"],
                env=process_env,
                check=True,
                capture_output=True,
                encoding="utf-8",
            )
            cached = subprocess.run(
                [*PYTHON_COMMAND, str(SCRIPT), "doctor", "--cached", "--json"],
                env=process_env,
                check=True,
                capture_output=True,
                encoding="utf-8",
            )
            cache_file = Path(temp_dir) / "doctor-cache.json"
            live_payload = json.loads(live.stdout)
            cached_payload = json.loads(cached.stdout)

            self.assertTrue(cache_file.is_file())
            if os.name != "nt":
                self.assertEqual(cache_file.stat().st_mode & 0o777, 0o600)

        self.assertNotIn("doctor-must-not-print-this-secret", live.stdout)
        self.assertFalse(live_payload["from_cache"])
        self.assertTrue(cached_payload["from_cache"])
        self.assertEqual(live_payload["config"]["directory"], temp_dir)
        self.assertEqual(
            live_payload["permissions"]["local_reads"]["browser_cookies"]["reads_values"],
            False,
        )
        self.assertIn("configuration", live_payload["permissions"]["local_reads"])
        self.assertIn(
            {"kind": "doctor_cache", "path": str(Path(temp_dir) / "doctor-cache.json")},
            live_payload["permissions"]["local_writes"],
        )
        self.assertTrue(live_payload["permissions"]["doctor_probe_commands"])
        self.assertEqual(
            cached_payload["permissions"]["local_reads"]["doctor_cache"]["status"],
            "read",
        )
        self.assertIn("sources", live_payload)

    def test_mock_saved_report_has_evidence_without_agent_scaffolding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            report_dir = Path(temp_dir) / "reports"
            process_env = {
                "PATH": os.environ.get("PATH", ""),
                "USER": os.environ.get("USER", ""),
                "HOME": temp_dir,
                "USERPROFILE": temp_dir,
                "LAST30DAYS_CONFIG_DIR": str(config_dir),
            }
            result = subprocess.run(
                [
                    *PYTHON_COMMAND,
                    str(SCRIPT),
                    "--mock",
                    "--emit=compact",
                    f"--save-dir={report_dir}",
                    "curated research tooling",
                ],
                env=process_env,
                check=True,
                capture_output=True,
                encoding="utf-8",
            )
            saved = sorted(report_dir.glob("*.md"))
            self.assertEqual(len(saved), 1)
            saved_text = saved[0].read_text(encoding="utf-8")

        self.assertIn("## Ranked Evidence Clusters", result.stdout)
        self.assertIn("## Source Coverage", result.stdout)
        self.assertNotIn("All agents reported back", result.stdout)
        self.assertNotIn("Best Takes", result.stdout)
        for source in ("Reddit", "X", "YouTube", "TikTok", "Hacker News", "GitHub", "Web"):
            self.assertIn(f"### {source}", saved_text)
        for removed_source in ("Instagram", "Bluesky", "arXiv", "Techmeme", "Trustpilot"):
            self.assertNotIn(f"### {removed_source}", saved_text)

    def test_removed_surfaces_and_old_namespaces_do_not_return(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
            and "vendor" not in path.parts
            and "__pycache__" not in path.parts
            and "tests" not in path.parts
            and path.suffix in {".py", ".md", ".yaml"}
        )
        self.assertNotIn(".claude/", text)
        self.assertNotIn("{VERSION}", text)
        self.assertNotIn("Named failure mode", text)
        self.assertNotIn("Observed violation", text)
        self.assertNotIn("How this version fixes", text)
        self.assertFalse((SKILL_ROOT / "scripts" / "lib" / "html_publish.py").exists())
        self.assertFalse((SKILL_ROOT / "scripts" / "lib" / "hosted.py").exists())
        for module in (
            "arxiv.py",
            "bluesky.py",
            "digg.py",
            "instagram.py",
            "linkedin.py",
            "perplexity.py",
            "pinterest.py",
            "setup_wizard.py",
            "stocktwits.py",
            "techmeme.py",
            "threads.py",
            "truthsocial.py",
            "trustpilot.py",
            "xiaohongshu_api.py",
        ):
            self.assertFalse((SKILL_ROOT / "scripts" / "lib" / module).exists())
        help_result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertNotIn("brief", help_result.stdout)
        self.assertNotIn("publish-html", help_result.stdout)
        self.assertNotIn("deep-research", help_result.stdout)
        self.assertNotIn("ig-creators", help_result.stdout)
        self.assertNotIn("trustpilot-domain", help_result.stdout)

    def test_runtime_source_contract_matches_advertised_sources(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import json, sys; "
                f"sys.path.insert(0, {str((SKILL_ROOT / 'scripts')).__repr__()}); "
                "from lib.pipeline import MOCK_AVAILABLE_SOURCES; "
                "print(json.dumps(MOCK_AVAILABLE_SOURCES))"
            ),
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        self.assertEqual(
            set(json.loads(result.stdout)),
            {"reddit", "x", "youtube", "tiktok", "hackernews", "polymarket", "github", "grounding"},
        )


if __name__ == "__main__":
    unittest.main()
