"""Focused config and scheduled task contract tests without task registration."""

import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[4] / "plugins" / "opl" / "skills" / "slop-buster" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import slop_config
import slop_setup


class SetupTests(unittest.TestCase):
    def test_load_config_defaults_and_isolated_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slop-buster.toml"
            path.write_text('data_repo = "C:\\\\audit"\nsource_homes = ["C:\\\\Users\\\\u\\\\.codex"]\n', encoding="utf-8")
            with patch.dict(os.environ, {"SLOP_BUSTER_CONFIG": str(path)}):
                config = slop_config.load_config()
            self.assertEqual(config["data_repo"], r"C:\audit")
            self.assertEqual(config["deadline_seconds"], 1800)
            self.assertEqual(config["schedule_time"], "09:00")
            self.assertEqual(config["timezone"], "America/Chicago")
            self.assertEqual(config["models"]["reader"], {"name": "gpt-5.6-luna", "effort": "medium"})

    def test_invalid_config_fails_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text('source_homes = []\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source_homes"):
                slop_config.load_config(str(path))
            with self.assertRaisesRegex(ValueError, "does not exist"):
                slop_config.load_config(str(Path(directory) / "missing.toml"))

    def test_windows_discovery_selects_ubuntu_and_excludes_docker(self):
        listing = "docker-desktop\nUbuntu-24.04\n".encode("utf-16-le")
        def run(command, **_kwargs):
            if "--list" in command:
                return type("Result", (), {"returncode": 0, "stdout": listing})()
            return type("Result", (), {"stdout": "/home/alice"})()
        with patch.object(slop_config.os, "name", "nt"), patch.object(slop_config.subprocess, "run", side_effect=run):
            home = slop_config._ubuntu_codex_home()
        self.assertEqual(home, r"\\wsl$\Ubuntu-24.04\home\alice\.codex")

    def test_wsl_reads_windows_config_home_for_same_distro(self):
        with patch.object(slop_config, "is_wsl", return_value=True), \
             patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu-24.04"}), \
             patch.object(slop_config.subprocess, "run") as command:
            path = slop_config.native_path(r"\\wsl$\Ubuntu-24.04\home\alice\.codex")
        self.assertEqual(path, "/home/alice/.codex")
        command.assert_not_called()

    def test_task_xml_has_logged_on_daily_recovery_contract(self):
        config = {"data_repo": r"C:\data repo", "schedule_time": "09:00"}
        xml = slop_setup.task_xml(config, Path(r"C:\config.toml"), "S-1-5-21-123")
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-16"?>'))
        self.assertEqual(slop_setup.ET.fromstring(xml.encode("utf-16")).tag,
                         "{" + slop_setup.TASK_NS + "}Task")
        self.assertIn("InteractiveToken", xml)
        self.assertIn("StartWhenAvailable", xml)
        self.assertIn("Parallel", xml)
        self.assertIn("09:00:00", xml)
        self.assertIn("-NoExit", xml)
        self.assertIn("--scheduled", xml)
        self.assertEqual(slop_setup._task_signature(xml), slop_setup._task_signature(xml))

    def test_wsl_reuses_matching_native_scheduler_config(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "slop-buster.toml"
            candidate.write_text('source_homes = ["home"]\n', encoding="utf-8")
            config = {"data_repo": "data", "source_homes": ["home"]}
            with patch.object(slop_setup, "is_wsl", return_value=True), \
                 patch.object(slop_setup, "_windows_codex_home", return_value=directory), \
                 patch.object(slop_setup, "load_config", return_value=config):
                selected = slop_setup._scheduler_config_path(config, Path("/home/user/.codex/slop-buster.toml"))
            self.assertEqual(selected, candidate)

    def test_existing_nonrepository_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "data"
            repo.mkdir()
            evidence = repo / "evidence.md"
            evidence.write_text("keep", encoding="utf-8")
            config_path = Path(directory) / "config.toml"
            config_path.write_text(f'data_repo = {json.dumps(str(repo))}\nsource_homes = [{json.dumps(str(Path(directory) / "home"))}]\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a Git repository"):
                slop_setup.setup(str(config_path), dry_run=True)
            self.assertEqual(evidence.read_text(encoding="utf-8"), "keep")

    def test_setup_reuses_dedicated_repo_without_wiping_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "data"
            config_path = Path(directory) / "config.toml"
            config_path.write_text(f'data_repo = {json.dumps(str(repo))}\nsource_homes = [{json.dumps(str(Path(directory) / "home"))}]\n', encoding="utf-8")
            with patch.object(slop_setup, "reconcile_task", return_value="unchanged"):
                first = slop_setup.setup(str(config_path))
                evidence = repo / "evidence.md"
                evidence.write_text("keep", encoding="utf-8")
                second = slop_setup.setup(str(config_path))
            self.assertEqual(first["task"], second["task"])
            self.assertTrue((repo / ".git").exists())
            self.assertEqual((repo / ".gitignore").read_text(encoding="utf-8").splitlines(),
                             [".runtime/", "index/", "feedback/"])
            self.assertEqual(evidence.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
