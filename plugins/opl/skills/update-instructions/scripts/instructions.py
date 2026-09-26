#!/usr/bin/env python3
"""Versioned OPL instruction inspection, ancestry lookup, and reviewed replacement."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid

MARKER = re.compile(r"^<!-- opl-instructions-version: ([1-9][0-9]*) -->$", re.MULTILINE)
SOURCE = "plugins/opl/AGENTS.md"
UPSTREAM = "https://github.com/OnePersonLabs/opl.git"
LEGACY_UPSTREAM = "https://github.com/OnePersonLabs/onepersonlabs-plugins.git"
EXTRACTION_VERSION = 10


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
    return {"home": str(home), "target": str(target), "sha256": hashlib.sha256(data).hexdigest() if data is not None else "missing",
            "user_version": previous, "bundled_version": current, "status": state, "error": error,
            "bundled_path": str(root / "AGENTS.md"), "bundled_sha256": hashlib.sha256(bundled).hexdigest()}


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.decode('utf-8', errors='replace').strip()}")
    return result.stdout


def historical(repo: Path, wanted: int) -> tuple[bytes, list[str]] | None:
    commits = git(repo, "log", "--all", "--full-history", "--format=%H", "--", SOURCE).decode().splitlines()
    found = {}
    for commit in commits:
        # A deletion commit has no file to inspect.
        if not git(repo, "ls-tree", commit, "--", SOURCE).strip():
            continue
        data = git(repo, "show", f"{commit}:{SOURCE}")
        try:
            number = version(data, optional=True)
        except ValueError:
            if re.search(rf"opl-instructions-version:\s*{wanted}(?![0-9])", normalized(data)):
                raise ValueError(f"malformed historical version {wanted} at {commit}") from None
            continue
        if number == wanted:
            key = normalized(data)
            found.setdefault(key, {"data": data, "commits": []})["commits"].append(commit)
    if len(found) > 1:
        raise ValueError(f"version {wanted} identifies different historical contents; cannot choose a baseline")
    if not found:
        return None
    match = next(iter(found.values()))
    return match["data"], match["commits"]


def baseline(wanted: int, output: Path, repo: Path | None) -> dict:
    match = historical(repo, wanted) if repo else None
    upstream = LEGACY_UPSTREAM if wanted < EXTRACTION_VERSION else UPSTREAM
    source = str(repo) if match else upstream
    if match is None:
        with tempfile.TemporaryDirectory(prefix="opl-instructions-history-") as directory:
            checkout = Path(directory) / "history.git"
            for attempt in range(2):
                result = subprocess.run(["git", "clone", "--bare", "--filter=blob:none", upstream, str(checkout)], capture_output=True, timeout=120)
                if result.returncode == 0:
                    break
                message = result.stderr.decode("utf-8", errors="replace").strip()
                transient = any(part in message.lower() for part in ("timed out", "could not resolve", "connection reset", "502", "503", "504"))
                if not transient or attempt == 1:
                    raise RuntimeError(f"upstream history retrieval failed: {message}")
                print(json.dumps({"warning": "history_retry", "attempt": attempt + 1, "error": message}), file=sys.stderr)
                # git removes a failed new clone; use a distinct path if it did not.
                checkout = Path(directory) / "retry.git"
                time.sleep(1)
            match = historical(checkout, wanted)
    if match is None:
        raise ValueError(f"no historical OPL AGENTS.md found with version {wanted}; initial reconciliation is required")
    data, commits = match
    # Never overwrite an existing artifact or a user's instructions during retrieval.
    with output.open("xb") as stream:
        stream.write(data)
    return {"version": wanted, "output": str(output.resolve()), "source": source, "commits": commits}


def apply_candidate(home: Path, root: Path, candidate: Path, expected: str, expected_target: str, expected_baseline: str) -> dict:
    before = snapshot(home, root)
    target = Path(before["target"])
    if before["sha256"] != expected or target != Path(expected_target).resolve() or before["bundled_sha256"] != expected_baseline:
        raise ValueError("user instructions changed since review; inspect and review the new diff")
    if target.is_symlink():
        raise ValueError("instruction target is a symlink; reconcile its destination explicitly")
    replacement = candidate.read_bytes()
    if version(replacement) != before["bundled_version"]:
        raise ValueError("candidate must record the installed OPL instructions version")
    if before["user_version"] and before["user_version"] > before["bundled_version"]:
        raise ValueError("refusing to downgrade a newer user baseline")
    if candidate.resolve() == target.resolve():
        raise ValueError("candidate must be a separate reviewed file")
    original = target.read_bytes() if target.exists() else None
    if original == replacement:
        return {"target": str(target), "changed": False, "backup": None}
    home.mkdir(parents=True, exist_ok=True)
    backup = None
    temporary = None
    try:
        if original is not None:
            backup = target.with_name(target.name + ".opl-backup-" + uuid.uuid4().hex)
            with backup.open("xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            backup.chmod(stat.S_IMODE(target.stat().st_mode))
        with tempfile.NamedTemporaryFile(dir=home, prefix=".opl-instructions-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        if original is not None:
            temporary.chmod(stat.S_IMODE(target.stat().st_mode))
        final = snapshot(home, root)
        if final["target"] != str(target) or final["sha256"] != expected or final["bundled_sha256"] != expected_baseline:
            raise ValueError("instructions or installed baseline changed during application; review again")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"target": str(target), "changed": True, "backup": str(backup) if backup else None,
            "version": before["bundled_version"], "sha256": hashlib.sha256(replacement).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "apply"):
        child = commands.add_parser(command)
        child.add_argument("--home")
        child.add_argument("--plugin-root")
        if command == "apply":
            child.add_argument("--candidate", type=Path, required=True)
            child.add_argument("--expected-sha256", required=True)
            child.add_argument("--expected-target", required=True)
            child.add_argument("--expected-baseline-sha256", required=True)
    child = commands.add_parser("baseline")
    child.add_argument("--version", type=int, required=True)
    child.add_argument("--repo", type=Path)
    child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "baseline":
        if args.version < 1:
            raise ValueError("version must be a positive integer")
        result = baseline(args.version, args.output, args.repo)
    elif args.command == "inspect":
        result = snapshot(home_path(args.home), plugin_path(args.plugin_root))
    else:
        result = apply_candidate(home_path(args.home), plugin_path(args.plugin_root), args.candidate, args.expected_sha256, args.expected_target, args.expected_baseline_sha256)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
