"""Configuration and host path resolution for the Slop Buster launcher."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib


DEFAULT_DATA_REPO = r"C:\dev\projects\slop-intelligence"
DEFAULT_MODELS = {
    "orchestrator": {"name": "gpt-6.1-sol", "effort": "medium"},
    "reader": {"name": "gpt-5.6-luna", "effort": "medium"},
    "synthesis": {"name": "gpt-6.1-sol", "effort": "high"},
}


def is_wsl() -> bool:
    if os.name == "nt":
        return False
    if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False


def native_path(value: str) -> str:
    """Translate a Windows path for WSL; leave native paths untouched."""
    if is_wsl() and value.lower().startswith("\\\\wsl$\\"):
        parts = value.split("\\")
        if len(parts) > 4 and parts[3].casefold() == os.environ.get("WSL_DISTRO_NAME", "").casefold():
            return "/" + "/".join(parts[4:])
    if is_wsl() and (re.match(r"^[A-Za-z]:[\\/]", value) or value.lower().startswith("\\\\wsl$\\")):
        result = subprocess.run(["wslpath", "-u", value], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    return str(Path(value).expanduser())


def config_file(config_path: str | None = None) -> Path:
    selected = config_path or os.environ.get("SLOP_BUSTER_CONFIG")
    if selected:
        return Path(native_path(selected))
    codex_home = os.environ.get("CODEX_HOME")
    return Path(native_path(codex_home)) / "slop-buster.toml" if codex_home else Path.home() / ".codex" / "slop-buster.toml"


def _windows_codex_home() -> str | None:
    if os.name == "nt":
        return str(Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    if not is_wsl():
        return None
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "[Environment]::GetFolderPath('UserProfile')"],
        capture_output=True, text=True, check=True,
    )
    return native_path(result.stdout.strip() + r"\.codex")


def _ubuntu_codex_home() -> str | None:
    if is_wsl():
        return str(Path.home() / ".codex") if "ubuntu" in os.environ.get("WSL_DISTRO_NAME", "ubuntu").lower() else None
    if os.name != "nt":
        return None
    listed = subprocess.run(["wsl.exe", "--list", "--quiet"], capture_output=True, check=False)
    if listed.returncode != 0:
        return None
    names = listed.stdout.decode("utf-16-le", errors="ignore").replace("\x00", "").splitlines()
    ubuntu = next((name.strip() for name in names if name.strip().lower().startswith("ubuntu")), None)
    if not ubuntu:
        return None
    home = subprocess.run(["wsl.exe", "-d", ubuntu, "--", "sh", "-c", 'printf %s "$HOME"'],
                          capture_output=True, text=True, check=True).stdout.strip()
    return rf"\\wsl$\{ubuntu}{home.replace('/', '\\')}\.codex"


def discover_source_homes() -> list[str]:
    homes = [_windows_codex_home(), _ubuntu_codex_home()]
    return list(dict.fromkeys(home for home in homes if home))


def load_config(config_path: str | None = None) -> dict:
    """Load a complete config; reject invalid explicit values and unreadable files."""
    path = config_file(config_path)
    if not path.is_file():
        raise ValueError(f"Slop Buster config does not exist: {path}; run setup")
    try:
        saved = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"Cannot load Slop Buster config {path}: {error}") from error
    if not isinstance(saved, dict):
        raise ValueError(f"Invalid Slop Buster config {path}")
    data_repo = saved.get("data_repo", DEFAULT_DATA_REPO)
    homes = saved.get("source_homes")
    deadline = saved.get("deadline_seconds", 1800)
    models = saved.get("models", {})
    if not isinstance(data_repo, str) or not data_repo.strip():
        raise ValueError("data_repo must be a nonempty path")
    if homes is None:
        homes = discover_source_homes()
    if not isinstance(homes, list) or not homes or any(not isinstance(home, str) or not home.strip() for home in homes):
        raise ValueError("source_homes must contain at least one path")
    if type(deadline) is not int or deadline <= 0:
        raise ValueError("deadline_seconds must be a positive integer")
    if not isinstance(models, dict):
        raise ValueError("models must be a table")
    resolved_models = {}
    for role, defaults in DEFAULT_MODELS.items():
        supplied = models.get(role, {})
        if not isinstance(supplied, dict):
            raise ValueError(f"models.{role} must be a table")
        resolved = {**defaults, **supplied}
        if any(not isinstance(resolved[key], str) or not resolved[key].strip() for key in ("name", "effort")):
            raise ValueError(f"models.{role} requires name and effort")
        resolved_models[role] = resolved
    return {
        "data_repo": native_path(data_repo),
        "source_homes": [native_path(home) for home in homes],
        "deadline_seconds": deadline,
        "models": resolved_models,
    }


if __name__ == "__main__":
    import json
    try:
        print(json.dumps(load_config(sys.argv[1] if len(sys.argv) > 1 else None)))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        sys.exit(2)
