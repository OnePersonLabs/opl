import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "plugins" / "opl" / "skills" / "probe-agent-profile-usage" / "scripts" / "profile_probe.py"
SPEC = importlib.util.spec_from_file_location("profile_probe", SCRIPT)
profile_probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = profile_probe
SPEC.loader.exec_module(profile_probe)


class ProfileProbeTests(unittest.TestCase):
    def test_discovers_config_references_and_directory_profiles_once(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            home = base / "home"
            repo = base / "repo"
            (home / "agents").mkdir(parents=True)
            (repo / ".codex" / "agents").mkdir(parents=True)
            shared = home / "agents" / "worker.toml"
            shared.write_text('name = "worker"\ndescription = "worker"\ndeveloper_instructions = "do work"\n', encoding="utf-8")
            (home / "config.toml").write_text('[agents.worker]\nconfig_file = "agents/worker.toml"\n', encoding="utf-8")
            (repo / ".codex" / "config.toml").write_text('[agents.alias]\nconfig_file = "../../home/agents/worker.toml"\n', encoding="utf-8")
            (repo / ".codex" / "agents" / "local.toml").write_text('name = "local"\ndescription = "local"\ndeveloper_instructions = "do work"\n', encoding="utf-8")

            found = profile_probe.discover(home, repo)

            self.assertEqual([profile.name for profile in found], ["local", "worker"])
            worker = next(profile for profile in found if profile.name == "worker")
            self.assertEqual(worker.path, shared.resolve())
            self.assertEqual(worker.aliases, ["alias"])
            self.assertEqual(len(found), 2)

    def test_discovery_rejects_distinct_profiles_with_the_same_name(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            home = base / "home"
            repo = base / "repo"
            (home / "agents").mkdir(parents=True)
            (repo / ".codex" / "agents").mkdir(parents=True)
            body = 'name = "duplicate"\ndescription = "duplicate"\ndeveloper_instructions = "work"\n'
            (home / "agents" / "one.toml").write_text(body, encoding="utf-8")
            (repo / ".codex" / "agents" / "two.toml").write_text(body, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate names"):
                profile_probe.discover(home, repo)

    def test_instrument_is_idempotent_and_restores_exact_profile_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            path = base / "worker.toml"
            original = b'name = "worker"\ndescription = "worker"\nmodel = "old-model"\nmodel_reasoning_effort = "high"\ndeveloper_instructions = """Do the task.\n"""\n'
            path.write_bytes(original)
            profile = profile_probe.Profile("worker", path)
            log = base / "receipts.jsonl"

            first = profile_probe.instrument([profile], log)
            instrumented = path.read_bytes()
            parsed = __import__("tomllib").loads(instrumented.decode("utf-8"))
            second = profile_probe.instrument([profile], log)

            self.assertEqual(first["status"], "instrumented")
            self.assertEqual(second["status"], "already_instrumented")
            self.assertEqual(parsed["model"], "gpt-6-luna")
            self.assertEqual(parsed["model_reasoning_effort"], "low")
            self.assertEqual(parsed["sandbox_mode"], "workspace-write")
            self.assertIn("parent_task_instruction", parsed["developer_instructions"])
            profile_probe.uninstrument(log)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(profile_probe._state_path(log).exists())

    def test_restore_refuses_to_overwrite_profile_changed_during_probe(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            path = base / "worker.toml"
            path.write_text('name = "worker"\ndescription = "worker"\ndeveloper_instructions = """Do task."""\n', encoding="utf-8")
            log = base / "receipts.jsonl"
            profile_probe.instrument([profile_probe.Profile("worker", path)], log)
            path.write_text(path.read_text(encoding="utf-8") + "# external change\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "left untouched"):
                profile_probe.uninstrument(log)
            self.assertIn("external change", path.read_text(encoding="utf-8"))

    def test_receipts_require_the_full_context_record(self):
        with tempfile.TemporaryDirectory() as root:
            log = Path(root) / "receipts.jsonl"
            valid = {
                "profile_name": "worker",
                "utc_time": "2026-09-30T12:00:00Z",
                "runtime_model": "unknown",
                "reasoning_effort": "unknown",
                "parent_context_visible": "unknown",
                "parent_context_receipt": "unknown",
                "parent_task_instruction": "Do the task",
            }
            log.write_text(json.dumps(valid) + "\n", encoding="utf-8")
            self.assertIn("worker", profile_probe._read_receipts(log))
            log.write_text('{"profile_name":"worker"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing"):
                profile_probe._read_receipts(log)


if __name__ == "__main__":
    unittest.main()
