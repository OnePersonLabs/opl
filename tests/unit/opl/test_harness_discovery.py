"""Discovery keeps native state separate from local availability evidence."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "plugins/opl/skills/configure-harness/scripts/discovery.py"


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("harness_discovery", MODULE)
        self.discovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.discovery)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "project"
        self.cwd.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.native = {"items": [], "complete": {"plugin": True, "skill": True, "mcp": True},
                       "diagnostics": []}
        self.backend = patch.object(self.discovery, "collect_inventory", side_effect=self._native)
        self.backend.start()
        self.addCleanup(self.backend.stop)
        self.registered = []
        self.registry = patch.object(self.discovery, "list_registered_marketplaces",
                                     side_effect=lambda cwd, home: self.registered)
        self.registry.start()
        self.addCleanup(self.registry.stop)

    def _native(self, cwd, *, codex_home):
        self.assertEqual(cwd, self.cwd)
        self.assertEqual(codex_home, self.home)
        return self.native

    def _json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def _skill(self, path, description="A useful skill"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: my-skill\ndescription: >-\n  {description}\n  For doing work.\n---\n\n# Body\n", encoding="utf-8")

    def test_native_states_and_skill_metadata_are_sanitized(self):
        skill = self.root / "installed" / "skills" / "my-skill" / "SKILL.md"
        self._skill(skill, "A useful skill with api_key=topsecret and Authorization: Bearer hiddenbearer")
        self.native["items"] = [
            {"kind": "plugin", "id": "alpha@market", "name": "alpha", "plugin": "alpha@market", "enabled": False},
            {"kind": "skill", "id": f"skill:alpha@market:{skill}", "name": "my-skill",
             "path": str(skill), "plugin": "alpha@market", "enabled": False},
            {"kind": "mcp", "id": "mcp:server", "name": "server", "plugin": None,
             "enabled": True, "transport": {"env": {"API_KEY": "secret"}}},
        ]
        result = self.discovery.discover(self.cwd, self.home, [], [])
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["complete"]["plugin"], True)
        native = [item for item in result["items"] if item["source"] == "native"]
        self.assertEqual([(item["kind"], item["enabled"]) for item in native],
                         [("mcp", True), ("plugin", False), ("skill", False)])
        skill_item = next(item for item in native if item["kind"] == "skill")
        self.assertEqual(skill_item["name"], "my-skill")
        self.assertIn("[redacted]", skill_item["description"])
        self.assertEqual(skill_item["textChars"], len(skill_item["description"]))
        self.assertEqual(skill_item["estimatedTokens"], (len(skill_item["description"]) + 3) // 4)
        self.assertNotIn("topsecret", json.dumps(result))
        self.assertNotIn("hiddenbearer", json.dumps(result))
        self.assertNotIn("transport", json.dumps(result))

    def test_cache_marketplace_and_standalone_are_not_treated_as_enabled(self):
        cache = self.home / "plugins" / "cache" / "market" / "alpha" / "1.0.0"
        self._json(cache / ".codex-plugin" / "plugin.json", {"name": "alpha", "description": "Cached alpha"})
        self._skill(cache / "skills" / "my-skill" / "SKILL.md")
        newer = cache.parent / "2.0.0"
        self._json(newer / ".codex-plugin" / "plugin.json", {"name": "alpha", "description": "Newer alpha"})
        local = self.cwd / "plugins" / "beta"
        self._json(local / ".codex-plugin" / "plugin.json", {"name": "beta", "description": "Local beta"})
        self._skill(local / "skills" / "my-skill" / "SKILL.md")
        self._skill(self.home / "skills" / "my-skill" / "SKILL.md")
        marketplace = self.cwd / ".agents" / "plugins" / "marketplace.json"
        self._json(marketplace, {"name": "market", "plugins": [
            {"name": "beta", "source": {"source": "local", "path": "./plugins/beta"}},
            {"name": "remote", "source": {"source": "url", "url": "https://example.invalid"}},
        ]})
        self.native["items"] = [{"kind": "plugin", "id": "alpha@market", "name": "alpha",
                                 "plugin": "alpha@market", "enabled": True}]
        result = self.discovery.discover(self.cwd, self.home, [marketplace], [])
        by_source = {source: [item for item in result["items"] if item["source"] == source]
                     for source in ("native", "cache", "marketplace", "filesystem")}
        self.assertEqual(len(by_source["native"]), 1)
        self.assertTrue(by_source["native"][0]["enabled"])
        self.assertEqual(len(by_source["cache"]), 3)
        cached_plugins = [item for item in by_source["cache"] if item["kind"] == "plugin"]
        self.assertEqual(len({item["id"] for item in cached_plugins}), 2)
        self.assertEqual({item["path"] for item in cached_plugins}, {str(cache), str(newer)})
        self.assertEqual(len(by_source["marketplace"]), 3)
        self.assertEqual(len(by_source["filesystem"]), 1)
        self.assertTrue(all(item["enabled"] is None for source in ("cache", "marketplace", "filesystem")
                            for item in by_source[source]))
        self.assertTrue(all(result["complete"].values()))

    def test_skill_policy_and_dependency_declarations_are_metadata_only(self):
        skill = self.home / "skills" / "my-skill" / "SKILL.md"
        self._skill(skill)
        skill.write_text("---\nname: my-skill\ndescription: A short description\ndependencies:\n  - git\n  - ripgrep\n---\n", encoding="utf-8")
        policy = skill.parent / "agents" / "openai.yaml"
        policy.parent.mkdir()
        policy.write_text("policy:\n  allow_implicit_invocation: false\ndependencies:\n  tools:\n    - name: docs\n      type: mcp\n      value: docs_search\n      description: Hidden detail\n", encoding="utf-8")
        result = self.discovery.discover(self.cwd, self.home, [], [])
        item = next(item for item in result["items"] if item["source"] == "filesystem")
        self.assertEqual(item["implicitInvocation"], False)
        self.assertEqual(item["dependencies"], ["git", "ripgrep"])
        self.assertEqual(item["declaredTools"], [{"name": "docs", "type": "mcp", "value": "docs_search"}])
        self.assertTrue(item["dependencyMetadataComplete"])
        self.assertNotIn("Hidden detail", json.dumps(result))
        self.assertIsNone(item["enabled"])

    def test_unsafe_dependency_value_is_not_emitted_and_marked_incomplete(self):
        skill = self.home / "skills" / "my-skill" / "SKILL.md"
        self._skill(skill)
        policy = skill.parent / "agents" / "openai.yaml"
        policy.parent.mkdir()
        policy.write_text("dependencies:\n  tools:\n    - name: docs\n      type: mcp\n      value: https://user:secret@example.test\n", encoding="utf-8")
        result = self.discovery.discover(self.cwd, self.home, [], [])
        item = next(item for item in result["items"] if item["source"] == "filesystem")
        self.assertFalse(item["dependencyMetadataComplete"])
        self.assertEqual(item["declaredTools"], [])
        self.assertNotIn("secret", json.dumps(result))

    def test_user_level_agents_skills_and_empty_registry_are_labeled(self):
        path = self.home.parent / ".agents" / "skills" / "my-skill" / "SKILL.md"
        self._skill(path)
        result = self.discovery.discover(self.cwd, self.home, [], [])
        item = next(item for item in result["items"] if item["source"] == "filesystem")
        self.assertEqual(item["path"], str(path))
        self.assertIsNone(item["enabled"])
        self.assertTrue(result["complete"]["marketplace"])

    def test_registered_marketplace_is_discovered_and_explicit_duplicate_is_deduplicated(self):
        marketplace = self.cwd / ".agents" / "plugins" / "marketplace.json"
        local = self.cwd / "plugins" / "beta"
        self._json(local / ".codex-plugin" / "plugin.json", {"name": "beta", "description": "Local beta"})
        self._json(marketplace, {"name": "market", "plugins": [
            {"name": "beta", "source": {"source": "local", "path": "./plugins/beta"}}]})
        self.registered = [self.cwd]
        result = self.discovery.discover(self.cwd, self.home, [marketplace], [])
        catalog = [item for item in result["items"] if item["source"] == "marketplace"]
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["path"], str(local))
        self.assertTrue(result["complete"]["marketplace"])
        self.assertEqual(result["scope"]["registeredMarketplaceRoots"], 1)
        self.assertEqual(result["scope"]["marketplaceManifestsScanned"], 1)

    def test_root_manifest_layout_and_missing_cache_manifest_are_distinguished(self):
        cache_root = self.home / "plugins" / "cache" / "local" / "projector" / "4.1.2"
        self._json(cache_root / "plugin.json", {"name": "projector", "description": "Root manifest"})
        missing = cache_root.parent / "4.0.0"
        missing.mkdir()
        local = self.cwd / "workflow-plugin"
        self._json(local / "plugin.json", {"name": "projector", "description": "Marketplace source"})
        marketplace = self.cwd / ".agents" / "plugins" / "marketplace.json"
        self._json(marketplace, {"name": "local", "plugins": [
            {"name": "projector", "source": {"source": "local", "path": "./workflow-plugin"}}]})
        self.registered = [self.cwd]
        result = self.discovery.discover(self.cwd, self.home, [], [])
        cached = next(item for item in result["items"] if item["source"] == "cache")
        catalog = next(item for item in result["items"] if item["source"] == "marketplace")
        self.assertEqual(cached["path"], str(cache_root))
        self.assertEqual(catalog["path"], str(local))
        self.assertFalse(result["complete"]["cache"])
        self.assertTrue(result["complete"]["marketplace"])
        missing_diagnostic = next(row for row in result["diagnostics"] if row["code"] == "cache_manifest_missing")
        self.assertEqual(missing_diagnostic["path"], "local/projector/4.0.0")
        self.assertNotIn(str(self.home), json.dumps(missing_diagnostic))

    def test_failed_registry_keeps_explicit_catalog_with_incomplete_scope(self):
        self.registry.stop()
        self.registry = patch.object(self.discovery, "list_registered_marketplaces",
                                     side_effect=ValueError("secret-bearing raw error"))
        self.registry.start()
        marketplace = self.cwd / ".agents" / "plugins" / "marketplace.json"
        self._json(marketplace, {"name": "market", "plugins": [
            {"name": "remote", "source": {"source": "url", "url": "https://example.invalid"}}]})
        result = self.discovery.discover(self.cwd, self.home, [marketplace], [])
        self.assertFalse(result["complete"]["marketplace"])
        self.assertIsNone(result["scope"]["registeredMarketplaceRoots"])
        self.assertEqual(len([item for item in result["items"] if item["source"] == "marketplace"]), 1)
        self.assertNotIn("secret-bearing", json.dumps(result))

    def test_registry_queries_only_native_local_list(self):
        self.registry.stop()
        with patch.object(self.discovery._inventory, "_command", return_value=["codex"]), \
             patch.object(self.discovery._inventory, "_cli",
                          return_value={"marketplaces": [{"name": "market", "root": str(self.cwd)}]}) as cli:
            roots = self.discovery.list_registered_marketplaces(self.cwd, self.home)
        self.assertEqual(roots, [self.cwd])
        self.assertEqual(cli.call_args.args[1], ["plugin", "marketplace", "list", "--json"])
        self.assertEqual(cli.call_args.args[3]["CODEX_HOME"], str(self.home))

    def test_partial_native_metadata_and_invalid_local_manifest_are_explicit(self):
        self.native["complete"]["skill"] = False
        self.native["diagnostics"] = [{"code": "codex_query_failed", "message": "Skill query failed.",
                                       "config": {"API_KEY": "never"}}]
        self._skill(self.cwd / ".agents" / "skills" / "my-skill" / "SKILL.md")
        marketplace = self.cwd / ".agents" / "plugins" / "api_marketplace.json"
        self._json(marketplace, {"plugins": [{"name": "unsafe", "source": {"source": "local", "path": "../escape"}}]})
        result = self.discovery.discover(self.cwd, self.home, [marketplace], [])
        self.assertFalse(result["complete"]["skill"])
        self.assertFalse(result["complete"]["marketplace"])
        self.assertIn("marketplace_invalid", [item["code"] for item in result["diagnostics"]])
        fallback = next(item for item in result["items"] if item["source"] == "filesystem")
        self.assertIsNone(fallback["enabled"])
        self.assertIn("project", fallback["path"])
        self.assertNotIn("never", json.dumps(result))

    def test_cli_check_is_explicit_and_does_not_execute_cli(self):
        with patch.object(self.discovery.shutil, "which", side_effect=lambda name: "C:/tools/git.exe" if name == "git" else None) as which:
            result = self.discovery.discover(self.cwd, self.home, [], ["git", "missing", "../invalid"])
        self.assertEqual(which.call_count, 2)
        clis = {item["name"]: item for item in result["items"] if item["kind"] == "cli"}
        self.assertTrue(clis["git"]["available"])
        self.assertFalse(clis["missing"]["available"])
        self.assertFalse(result["complete"]["cli"])


if __name__ == "__main__":
    unittest.main()
