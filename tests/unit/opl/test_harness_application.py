import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "harness_application", ROOT / "plugins/opl/skills/configure-harness/scripts/application.py"
)
application = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(application)


class HarnessApplication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        defaults = patch.object(application, "_load_config_defaults", return_value={
            "features": {"hooks": True, "plugins": True, "multi_agent": True},
            "agents": {
                "enabled": True,
                "default_subagent_model": "gpt-6-luna",
                "default_subagent_reasoning_effort": "medium",
            },
        })
        defaults.start()
        self.addCleanup(defaults.stop)

    def candidate(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_apply_and_rollback_exact_bytes_with_durable_receipt(self):
        agents = self.home / "AGENTS.md"
        old = b"\xef\xbb\xbf<!-- opl-instructions-version: 3 -->\r\nKeep rule.\r\n"
        agents.write_bytes(old)
        candidate = self.candidate("agents.candidate", old + application.MANAGED_HEADING.encode() + b"\r\nNew policy.\r\n")
        plan = application.prepare(self.home, [{"target": str(agents), "candidate": str(candidate)}])
        result = application.apply(self.home, plan)
        self.assertEqual(agents.read_bytes(), candidate.read_bytes())
        self.assertEqual(result["changed"], 1)
        receipt = Path(result["receipt"])
        self.assertTrue(receipt.is_file())
        self.assertEqual((receipt.parent / "0.backup").read_bytes(), old)
        self.assertEqual(application.rollback(self.home, receipt)["restored"], 1)
        self.assertEqual(agents.read_bytes(), old)

    def test_effective_override_and_installed_cache_denied(self):
        override = self.home / "AGENTS.override.md"
        override.write_bytes(b"Personal\n")
        main = self.home / "AGENTS.md"
        candidate = self.candidate("new.md", b"Personal\n" + application.MANAGED_HEADING.encode())
        with self.assertRaisesRegex(ValueError, "permitted"):
            application.prepare(self.home, [{"target": str(main), "candidate": str(candidate)}])
        application.prepare(self.home, [{"target": str(override), "candidate": str(candidate)}])
        cache = self.home / "plugins" / "cache" / "x.md"
        with self.assertRaisesRegex(ValueError, "permitted"):
            application.prepare(self.home, [{"target": str(cache), "candidate": str(candidate)}])

    def test_config_allows_only_enablement_and_preserves_other_parsed_values(self):
        config = self.home / "config.toml"
        original = b'''model = "gpt-6-sol"\n[plugins."opl"]\nsource = "marketplace"\n[mcp_servers.docs]\ncommand = "docs"\n[features]\nsandbox = true\n'''
        config.write_bytes(original)
        good = self.candidate("good.toml", b'''model = "gpt-6-sol"\n[plugins."opl"]\nsource = "marketplace"\nenabled = false\n[plugins."other"]\nenabled = true\n[mcp_servers.docs]\ncommand = "docs"\nenabled = false\n[features]\nsandbox = true\n[[skills.config]]\npath = "C:/skills/example"\nenabled = false\n''')
        application.prepare(self.home, [{"target": str(config), "candidate": str(good)}])
        bad = self.candidate("bad.toml", good.read_bytes().replace(b"sandbox = true", b"sandbox = false"))
        with self.assertRaisesRegex(ValueError, "outside allowed OPL"):
            application.prepare(self.home, [{"target": str(config), "candidate": str(bad)}])
        new_server = self.candidate("new-server.toml", original + b"\n[mcp_servers.unknown]\ncommand = 'evil'\nenabled = true\n")
        with self.assertRaisesRegex(ValueError, "new MCP"):
            application.prepare(self.home, [{"target": str(config), "candidate": str(new_server)}])

    def test_concurrent_edit_of_target_or_candidate_blocks_apply(self):
        target = self.home / "opl" / "harness" / "policies" / "one.md"
        candidate = self.candidate("one.md", b"approved")
        plan = application.prepare(self.home, [{"target": str(target), "candidate": str(candidate)}])
        target.parent.mkdir(parents=True)
        target.write_text("someone else")
        with self.assertRaisesRegex(ValueError, "changed since review"):
            application.apply(self.home, plan)
        self.assertEqual(target.read_text(), "someone else")
        target.unlink()
        candidate.write_text("changed")
        with self.assertRaisesRegex(ValueError, "candidate changed"):
            application.apply(self.home, plan)

    def test_symlink_and_unmanaged_instruction_edits_rejected(self):
        target = self.home / "AGENTS.md"
        target.write_text("Keep this.\n")
        candidate = self.candidate("candidate.md", b"Replace this.\n")
        with self.assertRaisesRegex(ValueError, "outside the managed"):
            application.prepare(self.home, [{"target": str(target), "candidate": str(candidate)}])
        policy_dir = self.home / "opl" / "harness" / "policies"
        policy_dir.parent.mkdir(parents=True)
        try:
            policy_dir.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "symlink"):
            application.prepare(self.home, [{"target": str(policy_dir / 'x.md'), "candidate": str(candidate)}])

    def test_managed_section_can_follow_missing_final_newline_only(self):
        target = self.home / "AGENTS.md"
        target.write_bytes(b"Keep this.")
        allowed = self.candidate("allowed.md", b"Keep this.\n" + application.MANAGED_HEADING.encode() + b"\nRule.\n")
        application.prepare(self.home, [{"target": str(target), "candidate": str(allowed)}])
        changed = self.candidate("changed.md", b"Changed.\n" + application.MANAGED_HEADING.encode() + b"\nRule.\n")
        with self.assertRaisesRegex(ValueError, "outside the managed"):
            application.prepare(self.home, [{"target": str(target), "candidate": str(changed)}])

    def test_existing_skill_without_enabled_remains_valid(self):
        config = self.home / "config.toml"
        config.write_bytes(b'[[skills.config]]\npath = "C:/skills/one"\n')
        candidate = self.candidate("skills.toml", b'[[skills.config]]\npath = "C:/skills/one"\n\n[[skills.config]]\npath = "C:/skills/two"\nenabled = false\n')
        application.prepare(self.home, [{"target": str(config), "candidate": str(candidate)}])
        changed = self.candidate("skills-changed.toml", b'[[skills.config]]\npath = "C:/skills/one"\nenabled = true\n')
        application.prepare(self.home, [{"target": str(config), "candidate": str(changed)}])

    def test_config_checker_policy_allows_only_its_features_defaults_and_opl_roles(self):
        config = self.home / "config.toml"
        config.write_bytes(b'''[features]\nhooks = false\nplugins = false\nmulti_agent = false\nother = true\n\n[agents]\nenabled = false\ndefault_subagent_model = "gpt-5.6-terra"\ndefault_subagent_reasoning_effort = "xhigh"\ninterrupt_message = true\n\n[agents.personal]\nconfig_file = "C:/personal.toml"\n\n[agents.opl-stale]\nconfig_file = "C:/old.toml"\n''')
        repaired = self.candidate("repaired.toml", b'''[features]\nhooks = true\nplugins = true\nmulti_agent = true\nother = true\n\n[agents]\nenabled = true\ndefault_subagent_model = "gpt-6-luna"\ndefault_subagent_reasoning_effort = "medium"\ninterrupt_message = true\n\n[agents.personal]\nconfig_file = "C:/personal.toml"\n\n[agents.opl-current]\nconfig_file = "C:/plugin/agents/current.toml"\n''')
        application.prepare(self.home, [{"target": str(config), "candidate": str(repaired)}])
        personal_change = self.candidate("personal-change.toml", repaired.read_bytes().replace(b"C:/personal.toml", b"C:/changed.toml"))
        with self.assertRaisesRegex(ValueError, "outside allowed OPL"):
            application.prepare(self.home, [{"target": str(config), "candidate": str(personal_change)}])
        extra_new_role_setting = self.candidate("extra-role.toml", repaired.read_bytes().replace(
            b'config_file = "C:/plugin/agents/current.toml"', b'config_file = "C:/plugin/agents/current.toml"\ndescription = "not allowed"'))
        with self.assertRaisesRegex(ValueError, "may only set config_file"):
            application.prepare(self.home, [{"target": str(config), "candidate": str(extra_new_role_setting)}])

    def test_config_checker_policy_requires_exact_scalar_types(self):
        config = self.home / "config.toml"
        config.write_bytes(b"[agents]\nenabled = false\nmax_depth = 1\n")
        wrong_boolean = self.candidate("wrong-boolean.toml", b"[agents]\nenabled = 1\nmax_depth = 1\n")
        with self.assertRaisesRegex(ValueError, "agents.enabled"):
            application.prepare(self.home, [{"target": str(config), "candidate": str(wrong_boolean)}])
        wrong_integer = self.candidate("wrong-integer.toml", b"[agents]\nenabled = false\nmax_depth = false\n")
        with patch.object(application, "_load_config_defaults", return_value={
            "features": {}, "agents": {"max_depth": 0},
        }):
            with self.assertRaisesRegex(ValueError, "agents.max_depth"):
                application.prepare(self.home, [{"target": str(config), "candidate": str(wrong_integer)}])

    def test_config_checker_policy_allows_managed_nested_feature_defaults_only(self):
        config = self.home / "config.toml"
        config.write_bytes(
            b"[features.current_time_reminder]\nenabled = false\nreminder_interval_seconds = 60\n"
        )
        repaired = self.candidate(
            "nested-feature.toml",
            b"[features.current_time_reminder]\nenabled = true\nreminder_interval_seconds = 300\n"
            b'delivery_mode = "any_inference"\n',
        )
        with patch.object(application, "_load_config_defaults", return_value={
            "features": {"current_time_reminder": {
                "enabled": True,
                "reminder_interval_seconds": 300,
                "delivery_mode": "any_inference",
            }},
            "agents": {},
        }):
            application.prepare(self.home, [{"target": str(config), "candidate": str(repaired)}])
            wrong = self.candidate(
                "wrong-nested-feature.toml",
                repaired.read_bytes().replace(b"reminder_interval_seconds = 300", b"reminder_interval_seconds = 301"),
            )
            with self.assertRaisesRegex(ValueError, "features.current_time_reminder.reminder_interval_seconds"):
                application.prepare(self.home, [{"target": str(config), "candidate": str(wrong)}])

    def test_config_checker_ignore_marker_is_a_versioned_top_insertion_or_removal_even_when_toml_is_invalid(self):
        config = self.home / "config.toml"
        config.write_bytes(b"[broken")
        allowed = self.candidate("ignored.toml", b"# opl:ignore-config-check version=0.2.0\n[broken")
        application.prepare(self.home, [{"target": str(config), "candidate": str(allowed)}])
        config.write_bytes(allowed.read_bytes())
        removed = self.candidate("removed.toml", b"[broken")
        application.prepare(self.home, [{"target": str(config), "candidate": str(removed)}])
        changed = self.candidate("changed.toml", b"[broken\n# another comment\n# opl:ignore-config-check version=0.2.0\n")
        with self.assertRaisesRegex(ValueError, "valid UTF-8 TOML"):
            application.prepare(self.home, [{"target": str(config), "candidate": str(changed)}])

    def test_rollback_refuses_later_user_edit_and_outside_receipt_target(self):
        target = self.home / "opl" / "harness" / "policies" / "one.md"
        candidate = self.candidate("one.md", b"approved")
        result = application.apply(self.home, application.prepare(self.home, [{"target": str(target), "candidate": str(candidate)}]))
        target.write_bytes(b"later user edit")
        with self.assertRaisesRegex(ValueError, "changed after application"):
            application.rollback(self.home, result["receipt"])
        self.assertEqual(target.read_bytes(), b"later user edit")
        receipt = Path(result["receipt"])
        record = __import__("json").loads(receipt.read_text())
        record["files"][0]["target"] = str(self.root / "outside.md")
        with self.assertRaisesRegex(ValueError, "does not match durable"):
            application.rollback(self.home, record)

    def test_later_write_failure_restores_earlier_target(self):
        one = self.home / "opl" / "harness" / "policies" / "one.md"
        two = self.home / "opl" / "harness" / "policies" / "two.md"
        one.parent.mkdir(parents=True)
        one.write_bytes(b"old one")
        two.write_bytes(b"old two")
        c1 = self.candidate("one.candidate", b"new one")
        c2 = self.candidate("two.candidate", b"new two")
        plan = application.prepare(self.home, [
            {"target": str(one), "candidate": str(c1)},
            {"target": str(two), "candidate": str(c2)},
        ])
        real_write = application._atomic_write
        def fail_second(path, data, mode=None):
            if path == two:
                raise OSError("second target locked")
            return real_write(path, data, mode)
        with patch.object(application, "_atomic_write", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second target locked"):
                application.apply(self.home, plan)
        self.assertEqual(one.read_bytes(), b"old one")
        self.assertEqual(two.read_bytes(), b"old two")

    def test_rollback_rechecks_each_target_before_restoring(self):
        policy_dir = self.home / "opl" / "harness" / "policies"
        policy_dir.mkdir(parents=True)
        one, two = policy_dir / "one.md", policy_dir / "two.md"
        one.write_bytes(b"old one")
        two.write_bytes(b"old two")
        c1 = self.candidate("one.candidate", b"new one")
        c2 = self.candidate("two.candidate", b"new two")
        plan = application.prepare(self.home, [
            {"target": str(one), "candidate": str(c1)},
            {"target": str(two), "candidate": str(c2)},
        ])
        result = application.apply(self.home, plan)
        real_write = application._atomic_write
        def concurrent_edit(path, data, mode=None):
            outcome = real_write(path, data, mode)
            if path == two:
                one.write_bytes(b"user changed after preflight")
            return outcome
        with patch.object(application, "_atomic_write", side_effect=concurrent_edit):
            with self.assertRaisesRegex(ValueError, "conflicting files were preserved"):
                application.rollback(self.home, result["receipt"])
        self.assertEqual(two.read_bytes(), b"old two")
        self.assertEqual(one.read_bytes(), b"user changed after preflight")


if __name__ == "__main__":
    unittest.main()
