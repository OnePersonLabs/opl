"""Exercise the public catalog command used by the skill."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[4] / "plugins/opl/skills/slop-buster/scripts"


class CatalogCliTests(unittest.TestCase):
    def test_umbrella_reads_selected_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "data"
            repo.mkdir()
            config = root / "slop-buster.toml"
            config.write_text('version = 1\ndata_repo = ' + json.dumps(repo.as_posix()) +
                              '\nsource_homes = [' + json.dumps(root.as_posix()) + ']\n', encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "slop.py"),
                                     "catalog", "validate", "--config", str(config)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), {"version": 0, "detectors": 0})

    def test_explicit_repository_does_not_require_user_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "slop.py"),
                                     "catalog", "--data-repo", directory, "validate"],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["detectors"], 0)


if __name__ == "__main__":
    unittest.main()
