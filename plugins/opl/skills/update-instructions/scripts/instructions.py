#!/usr/bin/env python3
"""Inspect and update the global OPL instructions."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid

MARKER = re.compile(r"^<!-- opl-instructions-version: ([1-9][0-9]*) -->$", re.MULTILINE)


def normalized(data: bytes) -> str:
    return data.decode("utf-8-sig").replace("\r\n", "\n")


def version(data: bytes, *, optional=False) -> int | None:
    text = normalized(data)
    matches = MARKER.findall(text)
    if not matches and "opl-instructions-version" not in text and optional:
        return None
    if len(matches) != 1 or text.count("opl-instructions-version") != 1:
        raise ValueError("expected exactly one valid <!-- opl-instructions-version: N --> marker")
    return int(matches[0])


def home_path(value=None) -> Path:
    return Path(value or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()


def effective_target(home: Path) -> Path:
    override = home / "AGENTS.override.md"
    if override.exists() and override.read_bytes().strip():
        return override
    return home / "AGENTS.md"


def plugin_path(value=None) -> Path:
    return Path(value or os.environ.get("PLUGIN_ROOT") or Path(__file__).resolve().parents[3]).resolve()


def snapshot(home: Path, root: Path) -> dict:
    target = effective_target(home)
    data = target.read_bytes() if target.exists() else None
    error = None
    try:
        previous = version(data, optional=True) if data is not None else None
    except (ValueError, UnicodeError) as exc:
        previous, error = None, str(exc)
    bundled = (root / "AGENTS.md").read_bytes()
    current = version(bundled)
    state = "invalid" if error else "setup" if previous is None else "current" if previous == current else "update" if previous < current else "newer"
    return {
        "home": str(home),
        "target": str(target),
        "sha256": hashlib.sha256(data).hexdigest() if data is not None else "missing",
        "user_version": previous,
        "bundled_version": current,
        "status": state,
        "error": error,
        "bundled_path": str(root / "AGENTS.md"),
        "bundled_sha256": hashlib.sha256(bundled).hexdigest(),
    }


def _backup_path(target: Path) -> Path:
    date = datetime.now().strftime("%Y%m%d")
    sequence = 1
    while True:
        candidate = target.with_name(f"{target.name}.opl-backup-{date}-{sequence:03d}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        sequence += 1


def apply_installed(home: Path, root: Path, expected: str, expected_target: str, expected_bundled: str) -> dict:
    before = snapshot(home, root)
    target = Path(before["target"])
    if (before["sha256"] != expected or target != Path(expected_target).resolve()
            or before["bundled_sha256"] != expected_bundled):
        raise ValueError("user instructions changed after inspection; inspect again before updating")
    if target.is_symlink():
        raise ValueError("instruction target is a symlink; reconcile its destination explicitly")

    source = root / "AGENTS.md"
    replacement = source.read_bytes()
    installed_version = version(replacement)
    if installed_version != before["bundled_version"]:
        raise ValueError("installed OPL instructions have an inconsistent version")
    if before["user_version"] is not None and before["user_version"] > installed_version:
        raise ValueError("refusing to downgrade a newer user instruction version")
    if source.resolve() == target.resolve():
        raise ValueError("installed instructions and effective target resolve to the same file")

    original = target.read_bytes() if target.exists() else None
    if original == replacement:
        return {"target": str(target), "changed": False, "backup": None}

    home.mkdir(parents=True, exist_ok=True)
    backup = None
    temporary = None
    try:
        if original is not None:
            while True:
                backup = _backup_path(target)
                try:
                    with backup.open("xb") as stream:
                        stream.write(original)
                        stream.flush()
                        os.fsync(stream.fileno())
                    break
                except FileExistsError:
                    continue
                except OSError:
                    backup.unlink(missing_ok=True)
                    raise
            backup.chmod(stat.S_IMODE(target.stat().st_mode))

        with tempfile.NamedTemporaryFile(dir=home, prefix=".opl-instructions-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        if original is not None:
            temporary.chmod(stat.S_IMODE(target.stat().st_mode))

        final = snapshot(home, root)
        if (final["target"] != str(target) or final["sha256"] != expected
                or final["bundled_sha256"] != expected_bundled):
            raise ValueError("instructions changed during application; update stopped")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return {
        "target": str(target),
        "changed": True,
        "backup": str(backup) if backup else None,
        "version": installed_version,
        "sha256": hashlib.sha256(replacement).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "apply"):
        child = commands.add_parser(command)
        child.add_argument("--home")
        child.add_argument("--plugin-root")
        if command == "apply":
            child.add_argument("--expected-sha256", required=True)
            child.add_argument("--expected-target", required=True)
            child.add_argument("--expected-bundled-sha256", required=True)
    args = parser.parse_args()
    home = home_path(args.home)
    root = plugin_path(args.plugin_root)
    if args.command == "inspect":
        result = snapshot(home, root)
    else:
        result = apply_installed(home, root, args.expected_sha256, args.expected_target,
                                 args.expected_bundled_sha256)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
