"""Integration checks for policy files, lifecycle output and session acknowledgments."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "opl"
sys.path.insert(0, str(PLUGIN / "scripts"))
spec = importlib.util.spec_from_file_location("compatibility_hook", PLUGIN / "scripts" / "codex-compatibility-check.py")
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def skill(name, plugin=None, enabled=True):
    qualified = f"{plugin.split('@')[0]}:{name}" if plugin else name
    return {"kind": "skill", "name": name, "qualifiedName": qualified,
            "plugin": plugin, "id": qualified, "enabled": enabled}


def last30days_owner(enabled=True):
    return dict(skill("last30days", "opl@opl", enabled),
                id="opl-owner", path=str(PLUGIN / "skills/last30days/SKILL.md"))


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="opl-compatibility-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home), "PLUGIN_DATA": str(self.root / "data")})
        self.env.start()
        self.inventory = {"items": [], "complete": {"plugin": True, "skill": True, "mcp": True}, "diagnostics": []}
        self.provider = patch.object(hook, "collect_inventory", side_effect=lambda *a, **kw: self.inventory)
        self.collect = self.provider.start()

    def tearDown(self):
        self.provider.stop()
        self.env.stop()
        self.temp.cleanup()

    def event(self, name="SessionStart", **kwargs):
        return hook.handle_event({"hook_event_name": name, "session_id": "session/one", "cwd": str(self.repo), "source": "startup", **kwargs}, plugin_root=PLUGIN)

    def policy(self, compatibility):
        directory = self.repo / ".opl"
        directory.mkdir(exist_ok=True)
        path = directory / "config.json"
        path.write_text(json.dumps({"codex": {"compatibility": compatibility}, "claude": {"other": True}}), encoding="utf-8")
        return path

    def conflict(self, enabled=True):
        self.inventory["items"] = [skill("debug", "opl@opl", enabled), skill("systematic-debugging", "superpowers@example")]

    def test_disabled_own_skill_allows_alternative(self):
        self.conflict(False)
        self.assertIsNone(self.event())

    def test_last30days_flags_every_other_enabled_copy(self):
        alternatives = [
            dict(skill("last30days"), id="standalone", path="/local/last30days/SKILL.md"),
            dict(skill("last30days", "research@market"), id="other-provider",
                 path="/plugins/research/skills/last30days/SKILL.md"),
            dict(skill("last30days", "opl@opl"), id="other-opl-copy",
                 path="/another/opl/skills/last30days/SKILL.md"),
        ]
        self.inventory["items"] = [last30days_owner(), *alternatives,
                                   skill("last30days", "disabled@market", False),
                                   skill("last30days-extended", "other@market")]
        report = hook.scan(self.repo, PLUGIN, self.home)
        self.assertEqual([item["code"] for item in report["findings"]], ["disallowed_enabled"])
        finding = report["findings"][0]
        self.assertEqual(finding["ruleId"], "opl.last30days.alternatives")
        self.assertEqual({item["id"] for item in finding["matches"]},
                         {"standalone", "other-provider", "other-opl-copy"})
        self.assertEqual(finding["source"], str(PLUGIN / "compatibility/skills/last30days.json"))
        warning = self.event()
        self.assertIn("opl.last30days.alternatives", warning["systemMessage"])
        self.assertIn("pause", warning["hookSpecificOutput"]["additionalContext"].lower())

    def test_last30days_does_not_reject_its_owner_or_disabled_alternatives(self):
        self.inventory["items"] = [last30days_owner(), skill("last30days", "other@market", False)]
        self.assertIsNone(self.event())

    def test_last30days_missing_or_disabled_owner_allows_other_copies(self):
        for owners in ([], [last30days_owner(False)]):
            with self.subTest(owners=owners):
                self.inventory["items"] = [*owners, skill("last30days"),
                    dict(skill("last30days", "opl@opl"),
                         id="other-opl-copy", path="/another/opl/skills/last30days/SKILL.md")]
                self.assertEqual(hook.scan(self.repo, PLUGIN, self.home)["findings"], [])

    def test_last30days_unknown_states_remain_unverifiable(self):
        scenarios = [
            ([last30days_owner(None), skill("last30days")], True, ["opl-owner"]),
            ([last30days_owner(), skill("last30days", "other@market", None)], True, ["other:last30days"]),
            ([last30days_owner()], False, []),
        ]
        for items, complete, expected_matches in scenarios:
            with self.subTest(items=items, complete=complete):
                self.inventory["items"] = items
                self.inventory["complete"]["skill"] = complete
                findings = [item for item in hook.scan(self.repo, PLUGIN, self.home)["findings"]
                            if item["ruleId"] == "opl.last30days.alternatives"]
                self.assertEqual([item["code"] for item in findings], ["cannot_verify"])
                self.assertEqual([item["id"] for item in findings[0]["matches"]], expected_matches)

    def test_last30days_rule_can_be_suppressed_with_a_reason(self):
        self.inventory["items"] = [last30days_owner(), skill("last30days")]
        self.policy({"version": 1, "ignoreRules": [{"id": "opl.last30days.alternatives",
                    "reason": "This repository compares both research workflows."}]})
        self.assertIsNone(self.event())

    def test_bundled_owner_path_binding_is_generic_and_rejects_escape(self):
        plugin = self.root / "bundled-plugin"
        policy_path = plugin / "compatibility/skills/review.json"
        policy_path.parent.mkdir(parents=True)
        value = {"version": 1, "rules": [{"id": "review.alternatives",
                 "whenEnabled": {"kind": "skill", "name": "review",
                                 "path": "${PLUGIN_ROOT}/skills/review/SKILL.md"},
                 "disallowed": [{"kind": "skill", "name": "review"}]}]}
        original = json.dumps(value)
        policy_path.write_text(original, encoding="utf-8")
        loaded, _, _ = hook.load_policy(self.repo, plugin)
        self.assertEqual(loaded["rules"][0]["whenEnabled"]["path"],
                         str(plugin / "skills/review/SKILL.md"))
        self.assertEqual(policy_path.read_text(encoding="utf-8"), original)
        value["rules"][0]["whenEnabled"]["path"] = "${PLUGIN_ROOT}/../outside/SKILL.md"
        policy_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(hook.PolicyError, r"/rules/0/whenEnabled/path: bundled owner path must resolve inside this plugin"):
            hook.load_policy(self.repo, plugin)

    def test_repository_owner_paths_do_not_expand_plugin_root(self):
        self.policy({"version": 1, "rules": [{"id": "repo.owner",
                     "whenEnabled": {"kind": "skill", "name": "last30days",
                                     "path": "${PLUGIN_ROOT}/skills/last30days/SKILL.md"}}]})
        with self.assertRaisesRegex(hook.PolicyError, "expected an absolute skill path"):
            hook.load_policy(self.repo, PLUGIN)

    def test_enabled_own_skill_warns_and_acknowledgment_preserves_task(self):
        self.conflict()
        warning = self.event()
        self.assertIn("systematic-debugging", warning["systemMessage"])
        self.assertIn("continue", warning["systemMessage"])
        first = self.event("UserPromptSubmit", prompt="Fix the private checkout bug")
        self.assertIn("pause", first["hookSpecificOutput"]["additionalContext"].lower())
        self.assertNotIn("decision", first)
        still_pending = self.event("UserPromptSubmit", prompt="the logs say ok but it still fails")
        self.assertIn("pause", still_pending["hookSpecificOutput"]["additionalContext"].lower())
        accepted = self.event("UserPromptSubmit", prompt="OK")
        self.assertIn("original", accepted["hookSpecificOutput"]["additionalContext"].lower())
        self.assertIsNone(self.event("UserPromptSubmit", prompt="now fix it"))
        state_files = list((self.root / "data").rglob("*.json"))
        self.assertTrue(state_files)
        for path in state_files:
            self.assertNotIn("private checkout", path.read_text(encoding="utf-8"))

    def test_resume_and_compaction_do_not_repeat_acknowledged_findings(self):
        self.conflict()
        self.event()
        self.event("UserPromptSubmit", prompt="continue")
        self.assertIsNone(self.event(source="compact"))
        self.assertIsNone(self.event(source="resume"))
        self.assertIsNotNone(self.event(source="clear"))

    def test_policy_change_invalidates_acknowledgment(self):
        self.conflict()
        self.event()
        self.event("UserPromptSubmit", prompt="continue")
        self.policy({"version": 1, "required": [{"kind": "plugin", "id": "needed@team"}]})
        output = self.event("UserPromptSubmit", prompt="continue coding")
        self.assertIn("needed@team", output["systemMessage"])
        self.assertIn("pause", output["hookSpecificOutput"]["additionalContext"].lower())

    def test_changed_findings_need_new_acknowledgment(self):
        self.conflict()
        self.event()
        self.event("UserPromptSubmit", prompt="continue")
        self.inventory["items"].append(skill("diagnosing-bugs"))
        self.assertIn("diagnosing-bugs", self.event(source="resume")["systemMessage"])

    def test_warning_mode_never_requests_pause(self):
        self.conflict()
        self.policy({"version": 1, "onViolation": "warn"})
        output = self.event()
        self.assertNotIn("reply", output["systemMessage"].lower())
        self.assertNotIn("pause", output["hookSpecificOutput"]["additionalContext"].lower())
        self.assertIsNone(self.event("UserPromptSubmit", prompt="fix it"))

    def test_recommendations_are_nonblocking(self):
        self.policy({"version": 1, "recommended": [{"kind": "skill", "name": "planning", "whenEnabled": {"required": [{"kind": "skill", "name": "implement"}]}}]})
        output = self.event()
        self.assertIn("planning", output["systemMessage"])
        self.assertNotIn("implement", output["systemMessage"])
        self.assertNotIn("pause", output["hookSpecificOutput"]["additionalContext"].lower())

    def test_project_policy_is_found_from_subdirectory(self):
        self.policy({"version": 1, "required": [{"kind": "mcp", "name": "docs", "plugin": "tools@team"}]})
        subdirectory = self.repo / "src"
        subdirectory.mkdir()
        output = self.event(cwd=str(subdirectory))
        self.assertIn("docs", output["systemMessage"])
        self.assertIn("mcp", self.collect.call_args.kwargs["kinds"])

    def test_default_policy_does_not_probe_mcp_inventory(self):
        self.event()
        self.assertEqual(self.collect.call_args.kwargs["kinds"], {"skill"})

    def test_disabled_owner_does_not_probe_its_nested_mcp_requirement(self):
        self.inventory["items"] = [skill("design", "workflow@team", False)]
        self.policy({"version": 1, "recommended": [{
            "kind": "skill", "name": "design", "plugin": "workflow@team",
            "whenEnabled": {"required": [{"kind": "mcp", "name": "docs", "plugin": "tools@team"}]}
        }]})
        output = self.event()
        self.assertNotIn("docs", output["systemMessage"])
        self.assertEqual(self.collect.call_count, 1)
        self.assertEqual(self.collect.call_args.kwargs["kinds"], {"skill"})

    def test_enabled_owner_discovers_its_nested_mcp_requirement(self):
        self.inventory["items"] = [skill("design", "workflow@team")]
        self.policy({"version": 1, "recommended": [{
            "kind": "skill", "name": "design", "plugin": "workflow@team",
            "whenEnabled": {"required": [{"kind": "mcp", "name": "docs", "plugin": "tools@team"}]}
        }]})
        output = self.event()
        self.assertIn("docs", output["systemMessage"])
        self.assertEqual(self.collect.call_count, 2)
        self.assertEqual(self.collect.call_args.kwargs["kinds"], {"skill", "mcp"})
        self.assertEqual(self.collect.call_args.kwargs["mcp_plugins"], {"tools@team"})

    def test_unknown_inventory_is_visible_and_not_claimed_missing(self):
        self.policy({"version": 1, "required": [{"kind": "mcp", "name": "docs"}]})
        self.inventory["complete"]["mcp"] = False
        self.inventory["diagnostics"] = [{"code": "codex_timeout", "kind": "mcp", "message": "MCP metadata query timed out"}]
        output = self.event()
        self.assertIn("timed out", output["systemMessage"])
        self.assertNotIn("required_missing", output["systemMessage"])

    def test_malformed_policy_is_loud_and_does_not_modify_configuration(self):
        path = self.policy({"version": 1})
        path.write_text('{"codex":', encoding="utf-8")
        output = self.event()
        self.assertIn("cannot read JSON", output["systemMessage"])
        self.assertIn("pause", output["hookSpecificOutput"]["additionalContext"])
        accepted = self.event("UserPromptSubmit", prompt="continue")
        self.assertIn("original", accepted["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(path.read_text(encoding="utf-8"), '{"codex":')

    def test_duplicate_json_keys_are_rejected(self):
        path = self.policy({"version": 1})
        path.write_text('{"codex":{"compatibility":{"version":1,"version":2}}}', encoding="utf-8")
        self.assertIn("duplicate", self.event()["systemMessage"])

    def test_large_findings_cache_round_trips(self):
        self.inventory["items"] = [dict(skill("debug"), id=f"copy-{i}") for i in range(30)]
        self.policy({"version": 1, "disallowed": [{"kind": "skill", "name": "debug"}] * 200})
        self.event()
        accepted = self.event("UserPromptSubmit", prompt="continue")
        self.assertIn("original", accepted["hookSpecificOutput"]["additionalContext"])
        for path in (self.root / "data").rglob("*.json"):
            self.assertLess(path.stat().st_size, 30000)

    def test_changing_working_directory_refreshes_discovery(self):
        child = self.repo / "child"
        child.mkdir()
        self.event()
        self.event("UserPromptSubmit", prompt="work here", cwd=str(child))
        self.assertEqual(self.collect.call_count, 2)

    def test_hook_errors_report_json_without_blocking_the_prompt(self):
        stdin = io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit"}))
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(stdout):
            result = hook.main([])
        self.assertEqual(result, 0)
        self.assertIn("could not complete", json.loads(stdout.getvalue())["systemMessage"])

    def test_warning_identifies_provider_and_explains_rule(self):
        self.conflict()
        message = self.event()["systemMessage"]
        self.assertIn("superpowers@example", message)
        self.assertIn("overlapping activation", message)

    def test_builtin_can_be_suppressed_with_reason(self):
        self.conflict()
        self.policy({"version": 1, "ignoreRules": [{"id": "opl.debug.alternatives", "reason": "We invoke both workflows explicitly."}]})
        self.assertIsNone(self.event())

    def test_check_json_exit_status_distinguishes_findings_from_errors(self):
        self.conflict()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = hook.main(["--check", "--json", "--cwd", str(self.repo)])
        self.assertEqual(status, 1)
        report = json.loads(output.getvalue())
        self.assertTrue(any(item["code"] == "disallowed_enabled" for item in report["findings"]))

    def test_repeated_prompt_uses_cache_and_separate_sessions_are_isolated(self):
        self.conflict()
        self.event()
        self.event("UserPromptSubmit", prompt="ok")
        self.event("UserPromptSubmit", prompt="continue")
        self.assertEqual(self.collect.call_count, 1)
        self.assertIsNotNone(self.event(session_id="session-two"))


if __name__ == "__main__":
    unittest.main()
