"""Focused config and local data repository setup tests."""

import json
import os
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
    def test_load_config_uses_isolated_config_and_default_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slop-buster.toml"
            path.write_text('data_repo = "C:\\\\audit"\nsource_homes = ["C:\\\\Users\\\\u\\\\.codex"]\n', encoding="utf-8")
            with patch.dict(os.environ, {"SLOP_BUSTER_CONFIG": str(path)}):
                config = slop_config.load_config()
            self.assertEqual(config["data_repo"], r"C:\audit")
            self.assertEqual(config["deadline_seconds"], 1800)

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

    def test_existing_nonrepository_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "data"
            repo.mkdir()
            evidence = repo / "evidence.md"
            evidence.write_text("keep", encoding="utf-8")
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                f'data_repo = {json.dumps(str(repo))}\nsource_homes = [{json.dumps(str(Path(directory) / "home"))}]\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not a Git repository"):
                slop_setup.setup(str(config_path), dry_run=True)
            self.assertEqual(evidence.read_text(encoding="utf-8"), "keep")

    def test_setup_initializes_repository_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "data"
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                f'data_repo = {json.dumps(str(repo))}\nsource_homes = [{json.dumps(str(Path(directory) / "home"))}]\n',
                encoding="utf-8",
            )
            first = slop_setup.setup(str(config_path))
            evidence = repo / "evidence.md"
            evidence.write_text("keep", encoding="utf-8")
            second = slop_setup.setup(str(config_path))

            self.assertEqual(first["data_repo"], second["data_repo"])
            self.assertEqual(first["status"], "initialized data repository")
            self.assertEqual(second["status"], "ready")
            self.assertTrue((repo / ".git").exists())
            self.assertEqual((repo / ".gitignore").read_text(encoding="utf-8").splitlines(),
                             [".runtime/", "index/", "feedback/"])
            self.assertEqual(evidence.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
