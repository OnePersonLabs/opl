import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "opl" / "scripts" / "codex-config-check.py"
SPEC = importlib.util.spec_from_file_location("codex_config_check", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ConfigCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.plugin = self.root / "opl"
        (self.plugin / "agents").mkdir(parents=True)
        manifest = self.plugin / ".codex-plugin"
        manifest.mkdir()
        (manifest / "plugin.json").write_text('{"name": "opl", "version": "0.2.0"}\n', encoding="utf-8")
        (self.plugin / "config.defaults.toml").write_text(
            '[features]\nmulti_agent = true\n\n[agents]\n'
            'default_subagent_model = "gpt-6-luna"\n'
            'default_subagent_reasoning_effort = "medium"\n',
            encoding="utf-8",
        )
        helper = self.plugin / "skills" / "configure-harness" / "scripts"
        helper.mkdir(parents=True)
        shutil.copy2(ROOT / "plugins" / "opl" / "skills" / "configure-harness" / "scripts" / "application.py",
                     helper / "application.py")

    @property
    def config(self):
        return self.home / "config.toml"

    def agent(self, filename, *, name=None, body=""):
        stem = Path(filename).stem
        expected = stem if stem.startswith("opl-") else f"opl-{stem}"
        (self.plugin / "agents" / filename).write_text(
            f'name = {json.dumps(name or expected)}\n'
            'description = "A test role."\n'
            'model = "gpt-6-luna"\n'
            'model_reasoning_effort = "high"\n'
            'developer_instructions = "Do the assigned work."\n'
            + body,
            encoding="utf-8",
        )

    def parsed(self):
        return tomllib.loads(self.config.read_text(encoding="utf-8-sig"))

    def test_reconcile_discovers_new_files_and_preserves_personal_agents(self):
        self.agent("existing.toml")
        self.agent("future-role.toml")
        self.config.write_text(
            "# keep this comment\n"
            "[agents]\n"
            "enabled = false\n"
            "default_subagent_model = \"gpt-5.6-terra\"\n"
            "default_subagent_reasoning_effort = \"xhigh\"\n"
            "interrupt_message = true\n\n"
            "[agents.personal]\n"
            "config_file = \"C:/personal.toml\"\n\n"
            "[agents.opl-existing]\n"
            "config_file = \"C:/old-plugin/agents/existing.toml\" # path moves\n\n"
            "[agents.opl-stale]\n"
            "config_file = \"C:/old-plugin/agents/stale.toml\"\n\n"
            "[features]\n"
            "hooks = false\nplugins = false\n",
            encoding="utf-8",
        )
        report, status = checker.command_reconcile(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertTrue(report["applied"]["changed"])
        result = self.parsed()
        self.assertEqual(result["agents"]["personal"]["config_file"], "C:/personal.toml")
        self.assertTrue(result["agents"]["interrupt_message"])
        self.assertNotIn("opl-stale", result["agents"])
        self.assertEqual(set(name for name in result["agents"] if name.startswith("opl-")),
                         {"opl-existing", "opl-future-role"})
        self.assertEqual(result["agents"]["opl-existing"]["config_file"],
                         str((self.plugin / "agents" / "existing.toml").resolve()))
        self.assertEqual(result["agents"]["opl-future-role"]["config_file"],
                         str((self.plugin / "agents" / "future-role.toml").resolve()))
        self.assertFalse(result["features"]["hooks"])
        self.assertIn("# keep this comment", self.config.read_text(encoding="utf-8"))

    def test_fix_sets_full_policy_and_accepts_effective_defaults(self):
        self.agent("role.toml")
        self.config.write_text(
            "[features]\nhooks = false\nplugins = false\n\n"
            "[agents]\ndefault_subagent_model = \"gpt-5.6-terra\"\n"
            "default_subagent_reasoning_effort = \"xhigh\"\n",
            encoding="utf-8",
        )
        report, status = checker.command_check(self.home, self.plugin)
        self.assertEqual(status, 1)
        self.assertNotIn("agents.enabled", [item["path"] for item in report["findings"]])
        self.assertNotIn("features.multi_agent", [item["path"] for item in report["findings"]])
        fixed, status = checker.command_fix(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertIn("applied", fixed)
        result = self.parsed()
        defaults = checker.load_defaults(self.plugin)
        self.assertEqual({key: result["features"][key] for key in defaults["features"]}, defaults["features"])
        self.assertEqual({key: result["agents"][key] for key in defaults["agents"]}, defaults["agents"])
        self.assertIn("opl-role", result["agents"])

    def test_shipped_defaults_apply_nested_features_and_luna_medium(self):
        plugin = ROOT / "plugins" / "opl"
        expected = {
            "features": {
                "multi_agent_v2": {
                    "enabled": True,
                    "hide_spawn_agent_metadata": False,
                    "expose_spawn_agent_model_overrides": True,
                    "min_wait_timeout_ms": 150000,
                    "default_wait_timeout_ms": 1500000,
                    "max_wait_timeout_ms": 1500000,
                },
                "apply_patch_preserve_line_endings": True,
                "code_mode": True,
                "code_mode_prewarm": True,
                "code_mode_interrupt": True,
                "code_mode_host": True,
            },
            "agents": {
                "enabled": True,
                "max_concurrent_threads_per_session": 6,
                "default_subagent_model": "gpt-6-luna",
                "default_subagent_reasoning_effort": "medium",
            },
        }
        self.assertEqual(checker.load_defaults(plugin), expected)
        application_spec = importlib.util.spec_from_file_location(
            "shipped_harness_application", plugin / "skills/configure-harness/scripts/application.py"
        )
        application = importlib.util.module_from_spec(application_spec)
        application_spec.loader.exec_module(application)
        self.assertEqual(application._load_config_defaults(), expected)
        self.config.write_text(
            'sandbox_mode = "workspace-write"\n'
            '[features]\nmulti_agent = false\nhooks = false\ncode_mode = false\n'
            '[features.current_time_reminder]\nenabled = false\nreminder_interval_seconds = 60\n'
            '[agents]\ndefault_subagent_model = "gpt-6-luna"\n'
            'default_subagent_reasoning_effort = "high"\n',
            encoding="utf-8",
        )
        report, status = checker.command_check(self.home, plugin)
        self.assertEqual(status, 1)
        self.assertNotIn("features.current_time_reminder.enabled", {item["path"] for item in report["findings"]})
        self.assertIn("features.multi_agent_v2", {item["path"] for item in report["findings"]})
        _, status = checker.command_fix(self.home, plugin)
        self.assertEqual(status, 0)
        result = self.parsed()
        for key, value in expected["features"].items():
            self.assertEqual(result["features"][key], value)
        self.assertFalse(result["features"]["current_time_reminder"]["enabled"])
        self.assertFalse(result["features"]["multi_agent"])
        self.assertFalse(result["features"]["hooks"])
        self.assertEqual(result["sandbox_mode"], "workspace-write")
        for key, value in expected["agents"].items():
            self.assertEqual(result["agents"][key], value)
        _, status = checker.command_check(self.home, plugin)
        self.assertEqual(status, 0)

    def test_invalid_complete_inventory_does_not_remove_registered_roles(self):
        self.config.write_text("[agents.opl-stale]\nconfig_file = \"C:/stale.toml\"\n", encoding="utf-8")
        (self.plugin / "agents" / "broken.toml").write_text(
            'name = "opl-other"\ndescription = "A test role."\ndeveloper_instructions = "Do work."\n', encoding="utf-8"
        )
        original = self.config.read_bytes()
        with self.assertRaisesRegex(checker.ConfigCheckError, "name must equal"):
            checker.command_reconcile(self.home, self.plugin)
        self.assertEqual(self.config.read_bytes(), original)

    def test_role_without_name_uses_its_filename_derived_registration(self):
        (self.plugin / "agents" / "unnamed.toml").write_text(
            'description = "A test role."\ndeveloper_instructions = "Do work."\n', encoding="utf-8"
        )
        self.assertEqual(checker.discover_agents(self.plugin), {
            "opl-unnamed": str((self.plugin / "agents" / "unnamed.toml").resolve()),
        })

    def test_versioned_ignore_marker_short_circuits_malformed_config_but_explicit_reconcile_does_not(self):
        self.agent("role.toml")
        self.config.write_text("# opl:ignore-config-check version=0.2.0\n[broken", encoding="utf-8")
        report, status = checker.command_check(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertTrue(report["ignored"])
        with self.assertRaisesRegex(checker.ConfigCheckError, "not valid TOML"):
            checker.command_reconcile(self.home, self.plugin)

    def test_ignore_marker_uses_bom_crlf_and_schema_position(self):
        self.config.write_bytes(
            b"\xef\xbb\xbf#:schema https://developers.openai.com/codex/config-schema.json\r\n\r\n"
            b"# General documentation\r\nmodel = \"gpt-6.1-sol\"\r\n"
        )
        report, status = checker.command_ignore(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertTrue(report["ignored"])
        self.assertEqual(
            self.config.read_bytes(),
            b"\xef\xbb\xbf#:schema https://developers.openai.com/codex/config-schema.json\r\n"
            b"# opl:ignore-config-check version=0.2.0\r\n\r\n"
            b"# General documentation\r\nmodel = \"gpt-6.1-sol\"\r\n",
        )

    def test_stale_marker_is_removed_then_the_audit_resumes(self):
        self.agent("role.toml")
        role_path = json.dumps(str((self.plugin / "agents" / "role.toml").resolve()))
        self.config.write_text(
            "# opl:ignore-config-check version=0.1.0\n"
            "[features]\nhooks = true\nplugins = true\nmulti_agent = true\n"
            "[agents]\nenabled = true\ndefault_subagent_model = \"gpt-6-luna\"\n"
            "default_subagent_reasoning_effort = \"medium\"\n"
            f"[agents.opl-role]\nconfig_file = {role_path}\n",
            encoding="utf-8",
        )
        report, status = checker.command_check(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertTrue(report["compliant"])
        self.assertEqual(report["removed_ignore_markers"], ["0.1.0"])
        self.assertNotIn("opl:ignore-config-check", self.config.read_text(encoding="utf-8"))

    def test_defaults_file_drives_repair_without_engine_changes(self):
        self.agent("role.toml")
        (self.plugin / "config.defaults.toml").write_text(
            "[features]\nhooks = false\n\n[agents]\ndefault_subagent_model = \"gpt-6.1-sol\"\nmax_depth = 3\n",
            encoding="utf-8",
        )
        self.config.write_text("[features]\nhooks = true\n\n[agents]\ndefault_subagent_model = \"gpt-6-luna\"\nmax_depth = 1\n", encoding="utf-8")
        report, status = checker.command_check(self.home, self.plugin)
        self.assertEqual(status, 1)
        self.assertEqual({item["path"] for item in report["findings"] if item["code"] == "setting_mismatch"},
                         {"features.hooks", "agents.default_subagent_model", "agents.max_depth"})
        fixed, status = checker.command_fix(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertIn("applied", fixed)
        result = self.parsed()
        self.assertFalse(result["features"]["hooks"])
        self.assertEqual(result["agents"]["default_subagent_model"], "gpt-6.1-sol")
        self.assertEqual(result["agents"]["max_depth"], 3)

    def test_policy_settings_require_exact_scalar_types(self):
        self.agent("role.toml")
        (self.plugin / "config.defaults.toml").write_text(
            "[agents]\nenabled = true\nmax_depth = 0\n",
            encoding="utf-8",
        )
        self.config.write_text("[agents]\nenabled = 1\nmax_depth = false\n", encoding="utf-8")
        report, status = checker.command_check(self.home, self.plugin)
        self.assertEqual(status, 1)
        self.assertEqual(
            {item["path"] for item in report["findings"] if item["code"] == "setting_mismatch"},
            {"agents.enabled", "agents.max_depth"},
        )
        _fixed, status = checker.command_fix(self.home, self.plugin)
        self.assertEqual(status, 0)
        result = self.parsed()["agents"]
        self.assertIs(result["enabled"], True)
        self.assertIs(type(result["max_depth"]), int)
        self.assertEqual(result["max_depth"], 0)

    def test_marker_text_inside_a_toml_string_is_never_removed(self):
        self.config.write_text(
            "[agents]\nnotes = \"\"\"\n# opl:ignore-config-check version=0.1.0\n\"\"\"\n",
            encoding="utf-8",
        )
        original = self.config.read_bytes()
        _report, status = checker.command_check(self.home, self.plugin)
        self.assertEqual(status, 1)
        self.assertEqual(self.config.read_bytes(), original)

    def test_removing_stale_role_keeps_comments_for_next_table(self):
        text = (
            "[agents.opl-stale]\nconfig_file = \"C:/stale.toml\"\n\n"
            "# Personal configuration remains below.\n\n"
            "[agents.personal]\nconfig_file = \"C:/personal.toml\"\n"
        )
        rendered = checker._remove_table(text, ("agents", "opl-stale"))
        self.assertEqual(rendered, "\n# Personal configuration remains below.\n\n[agents.personal]\nconfig_file = \"C:/personal.toml\"\n")

    def test_hook_is_silent_when_compliant_and_suppresses_subagents(self):
        self.agent("role.toml")
        self.config.write_text(
            "[features]\nhooks = true\nplugins = true\nmulti_agent = true\n"
            "[agents]\nenabled = true\ndefault_subagent_model = \"gpt-6-luna\"\n"
            "default_subagent_reasoning_effort = \"medium\"\n"
            f"[agents.opl-role]\nconfig_file = {json.dumps(str((self.plugin / 'agents' / 'role.toml').resolve()))}\n",
            encoding="utf-8",
        )
        previous = __import__("sys").stdin
        self.addCleanup(setattr, __import__("sys"), "stdin", previous)
        __import__("sys").stdin = io.StringIO(json.dumps({"hook_event_name": "SessionStart"}))
        output, status = checker.command_hook(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertEqual(output, {})
        __import__("sys").stdin = io.StringIO(json.dumps({"hook_event_name": "SessionStart", "agent_id": "child"}))
        output, status = checker.command_hook(self.home, self.plugin)
        self.assertEqual(status, 0)
        self.assertEqual(output, {"suppressed": True})

    def test_main_returns_nonzero_for_reconcile_failure(self):
        self.config.write_text("[agents.opl-stale]\nconfig_file = \"C:/stale.toml\"\n", encoding="utf-8")
        (self.plugin / "agents" / "bad.toml").write_text("description = []\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "reconcile", "--home", str(self.home), "--plugin-root", str(self.plugin)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("codex-config-check:", result.stderr)


if __name__ == "__main__":
    unittest.main()
