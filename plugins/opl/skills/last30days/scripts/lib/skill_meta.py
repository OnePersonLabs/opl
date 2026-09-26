"""Metadata for the plugin installation containing this executable."""

from __future__ import annotations

import json
from pathlib import Path


def read_plugin_version(start_path: str | Path) -> str | None:
    """Read the nearest enclosing Codex plugin manifest version.

    Resolution begins at the actual caller-provided file or directory and only
    walks its ancestors. It never searches Codex cache directories or chooses
    among multiple installed copies.
    """
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent

    for directory in (current, *current.parents):
        manifest = directory / ".codex-plugin" / "plugin.json"
        if not manifest.is_file():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        version = payload.get("version")
        return version.strip() if isinstance(version, str) and version.strip() else None
    return None
