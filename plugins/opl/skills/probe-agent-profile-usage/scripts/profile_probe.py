#!/usr/bin/env python3
"""Discover, temporarily instrument, and run a bounded Codex profile probe."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BEGIN = "OPL_AGENT_PROFILE_PROBE_BEGIN"
END = "OPL_AGENT_PROFILE_PROBE_END"
FIELD_MARKER = "# opl-agent-profile-probe-field:"
MODEL = "gpt-6-luna"
EFFORT = "low"
SANDBOX = "workspace-write"


@dataclass
class Profile:
    name: str
    path: Path
    sources: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


def _toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Cannot read valid UTF-8 TOML at {path}: {exc}") from exc


def _profile_name(path: Path) -> str:
    data = _toml(path)
    name = data.get("name")
    return name if isinstance(name, str) and name.strip() else path.stem


def discover(home: Path, repo: Path) -> list[Profile]:
    """Union explicit config_file references and Codex's profile directories."""
    profiles: dict[str, Profile] = {}

    def add(path: Path, source: str, alias: str | None = None) -> None:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"Discovered profile does not exist: {resolved} (from {source})")
        key = os.path.normcase(str(resolved))
        profile = profiles.get(key)
        if profile is None:
            profile = Profile(_profile_name(resolved), resolved)
            profiles[key] = profile
        if source not in profile.sources:
            profile.sources.append(source)
        if alias and alias != profile.name and alias not in profile.aliases:
            profile.aliases.append(alias)

    configs = [(home / "config.toml", "user config")]
    repo_config = repo / ".codex" / "config.toml"
    configs.append((repo_config, "repo config"))
    for config_path, label in configs:
        config = _toml(config_path)
        agents = config.get("agents", {})
        if agents is None:
            continue
        if not isinstance(agents, dict):
            raise ValueError(f"Expected [agents.<name>] tables in {config_path}")
        for name, settings in agents.items():
            if not isinstance(settings, dict):
                continue
            reference = settings.get("config_file")
            if reference is None:
                continue
            if not isinstance(reference, str):
                raise ValueError(f"agents.{name}.config_file must be a string in {config_path}")
            add(config_path.parent / reference, f"{label}: agents.{name}.config_file", name)

    for directory, label in ((home / "agents", "user .codex/agents"),
                             (repo / ".codex" / "agents", "repo .codex/agents")):
        if directory.is_dir():
            for path in sorted(directory.glob("*.toml"), key=lambda p: p.name.casefold()):
                add(path, label)

    result = sorted(profiles.values(), key=lambda p: (p.name.casefold(), str(p.path).casefold()))
    by_name: dict[str, list[Profile]] = {}
    for profile in result:
        by_name.setdefault(profile.name.casefold(), []).append(profile)
    duplicates = [group for group in by_name.values() if len(group) > 1]
    if duplicates:
        details = "; ".join(f"{group[0].name}: " + ", ".join(str(item.path) for item in group) for group in duplicates)
        raise ValueError(f"Distinct profile files declare duplicate names; resolve before probing: {details}")
    return result


def _json_text(value: str) -> str:
    # JSON basic strings are valid TOML basic strings and preserve arbitrary text.
    return json.dumps(value, ensure_ascii=False)


def _instruction_span(source: str) -> tuple[int, int, str, str] | None:
    """Return value start/end, delimiter, and decoded string for the root field."""
    match = re.search(r"(?m)^([ \t]*)developer_instructions[ \t]*=[ \t]*", source)
    if not match:
        return None
    # This field is conventionally a profile-level field. Reject a table-local one.
    preceding_tables = list(re.finditer(r"(?m)^\s*\[\[?.*\]\]?\s*(?:#.*)?$", source[:match.start()]))
    if preceding_tables:
        return None
    start = match.end()
    if source.startswith('"""', start):
        delimiter = '"""'
    elif source.startswith("'''", start):
        delimiter = "'''"
    elif source.startswith('"', start):
        delimiter = '"'
    elif source.startswith("'", start):
        delimiter = "'"
    else:
        raise ValueError("developer_instructions must be a TOML string")

    cursor = start + len(delimiter)
    while cursor < len(source):
        if source.startswith(delimiter, cursor):
            slashes = 0
            before = cursor - 1
            while before >= start and source[before] == "\\":
                slashes += 1
                before -= 1
            if delimiter in ("'", '"') and slashes % 2:
                cursor += len(delimiter)
                continue
            end = cursor
            try:
                decoded = tomllib.loads(source[match.start():end + len(delimiter)] + "\n")["developer_instructions"]
            except (KeyError, tomllib.TOMLDecodeError) as exc:
                raise ValueError(f"Cannot parse developer_instructions string: {exc}") from exc
            return start, end, delimiter, decoded
        cursor += 1
    raise ValueError("Unterminated developer_instructions string")


def _probe_block(log_path: Path, names: list[str]) -> str:
    target = str(log_path.resolve())
    allowed = json.dumps(names, ensure_ascii=False)
    return f'''{BEGIN}
Before any task work, append exactly one JSONL record to {target!r}. Use the exact profile name under which this profile was invoked; valid profile names from this file are {allowed}. Record the current UTC time in ISO 8601, runtime model and reasoning effort only when directly visible to you (otherwise "unknown"), whether parent/session messages beyond this assignment are actually visible, and a rough count and type of those visible messages. Do not infer context history from configuration. Include the verbatim task-specific instruction message received from your parent. Do not include these probe instructions, developer instructions, or system instructions in that quoted field. Append the record to the file; do not merely report it in your final answer.
Use JSON keys: profile_name, utc_time, runtime_model, reasoning_effort, parent_context_visible, parent_context_receipt, parent_task_instruction. Do not print the record or repeat the quoted task in your answer.
{END}'''


def _field_line(key: str, value: str, previous: str | None) -> str:
    encoded = "absent" if previous is None else base64.urlsafe_b64encode(previous.encode("utf-8")).decode("ascii")
    return f'{key} = {json.dumps(value)} {FIELD_MARKER}{key}:{encoded}'


def _instrument_text(text: str, log_path: Path, profile_names: list[str]) -> str:
    if BEGIN in text or FIELD_MARKER in text:
        raise ValueError("Profile already has probe markers but no matching state manifest; refusing to stack changes")
    data = tomllib.loads(text)
    instruction_value = data.get("developer_instructions")
    if not isinstance(instruction_value, str):
        raise ValueError("Profile must define a root-level developer_instructions string")
    span = _instruction_span(text)
    if span is None:
        raise ValueError("Could not locate root-level developer_instructions assignment")
    start, end, delimiter, decoded = span
    if decoded != instruction_value:
        raise ValueError("Could not safely match developer_instructions source to its parsed value")
    block = _probe_block(log_path, profile_names)
    if BEGIN in decoded or END in decoded:
        raise ValueError("Profile already contains a probe block without recognized field markers")
    if delimiter in ('"', "'"):
        replacement = _json_text(decoded.rstrip() + "\n\n" + block + "\n")
        text = text[:start] + replacement + text[end + len(delimiter):]
    else:
        text = text[:end] + "\n\n" + block + "\n" + text[end:]

    lines = text.splitlines()
    root_end = next((i for i, line in enumerate(lines) if re.match(r"\s*\[\[?.*\]\]?\s*(?:#.*)?$", line)), len(lines))
    for key, value in (("model", MODEL), ("model_reasoning_effort", EFFORT), ("sandbox_mode", SANDBOX)):
        matches = [i for i, line in enumerate(lines[:root_end]) if re.match(rf"^\s*{re.escape(key)}\s*=", line)]
        if len(matches) > 1:
            raise ValueError(f"Multiple root-level {key} fields in profile")
        previous = lines[matches[0]] if matches else None
        new_line = _field_line(key, value, previous)
        if matches:
            lines[matches[0]] = new_line
        else:
            lines.insert(root_end, new_line)
            root_end += 1
    result = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    tomllib.loads(result)
    return result


def _state_path(log_path: Path) -> Path:
    return log_path.with_name(log_path.name + ".state.json")


def instrument(profiles: list[Profile], log_path: Path) -> dict[str, Any]:
    state_path = _state_path(log_path)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if all(Path(item["path"]).is_file() and _sha(Path(item["path"]).read_bytes()) == item["instrumented_sha256"] for item in state["files"]):
            return {"status": "already_instrumented", "state": str(state_path), "profiles": [item["profile"] for item in state["files"]]}
        raise ValueError(f"State exists but instrumented files changed; restore or inspect them before proceeding: {state_path}")
    if not profiles:
        raise ValueError("No agent profiles discovered")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size:
        raise ValueError(f"Probe log must be empty or absent: {log_path}")
    changes: list[tuple[Profile, bytes, bytes]] = []
    for profile in profiles:
        original = profile.path.read_bytes()
        updated_text = _instrument_text(original.decode("utf-8"), log_path, [profile.name, *profile.aliases])
        changes.append((profile, original, updated_text.encode("utf-8")))
    state = {
        "schema": 1,
        "log": str(log_path.resolve()),
        "files": [{"profile": p.name, "path": str(p.path), "original_base64": base64.b64encode(old).decode("ascii"), "instrumented_sha256": _sha(new)} for p, old, new in changes],
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(state_path, (json.dumps(state, indent=2) + "\n").encode("utf-8"))
    written: list[tuple[Path, bytes]] = []
    try:
        for profile, original, updated in changes:
            _atomic_write(profile.path, updated)
            written.append((profile.path, original))
    except Exception:
        for path, original in reversed(written):
            _atomic_write(path, original)
        state_path.unlink(missing_ok=True)
        raise
    return {"status": "instrumented", "state": str(state_path), "profiles": [p.name for p, _, _ in changes]}


def uninstrument(log_path: Path) -> dict[str, Any]:
    state_path = _state_path(log_path)
    if not state_path.is_file():
        raise ValueError(f"No probe state to restore: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    restores: list[tuple[Path, bytes]] = []
    conflicts: list[str] = []
    for item in state.get("files", []):
        path = Path(item["path"])
        if not path.is_file():
            conflicts.append(f"missing profile: {path}")
            continue
        current = path.read_bytes()
        if _sha(current) != item["instrumented_sha256"]:
            conflicts.append(f"profile changed after instrumentation; left untouched: {path}")
            continue
        restores.append((path, base64.b64decode(item["original_base64"])))
    if conflicts:
        raise ValueError("Cannot safely restore all profiles:\n" + "\n".join(conflicts))
    for path, original in restores:
        _atomic_write(path, original)
    state_path.unlink()
    return {"status": "restored", "profiles": [str(path) for path, _ in restores]}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_receipts(log_path: Path, start_offset: int = 0) -> dict[str, dict[str, Any]]:
    receipts: dict[str, dict[str, Any]] = {}
    if not log_path.is_file():
        return receipts
    with log_path.open("rb") as stream:
        stream.seek(start_offset)
        new_content = stream.read().decode("utf-8")
    for number, line in enumerate(new_content.splitlines(), start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL record at {log_path}:{number}: {exc}") from exc
        if not isinstance(entry, dict) or not isinstance(entry.get("profile_name"), str):
            raise ValueError(f"Receipt at {log_path}:{number} has no profile_name")
        required = ("utc_time", "runtime_model", "reasoning_effort", "parent_context_visible",
                    "parent_context_receipt", "parent_task_instruction")
        missing = [key for key in required if key not in entry]
        if missing:
            raise ValueError(f"Receipt at {log_path}:{number} is missing: {', '.join(missing)}")
        if not all(isinstance(entry[key], str) and entry[key].strip() for key in
                   ("profile_name", "utc_time", "runtime_model", "reasoning_effort",
                    "parent_context_receipt", "parent_task_instruction")):
            raise ValueError(f"Receipt at {log_path}:{number} has empty or invalid text fields")
        if not isinstance(entry["parent_context_visible"], (bool, str)):
            raise ValueError(f"Receipt at {log_path}:{number} has invalid parent_context_visible")
        if isinstance(entry["parent_context_visible"], str) and entry["parent_context_visible"].casefold() not in {"yes", "no", "unknown"}:
            raise ValueError(f"Receipt at {log_path}:{number} parent_context_visible must be yes, no, or unknown")
        try:
            parsed_time = datetime.fromisoformat(entry["utc_time"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Receipt at {log_path}:{number} has invalid ISO 8601 utc_time") from exc
        if parsed_time.utcoffset() is None:
            raise ValueError(f"Receipt at {log_path}:{number} utc_time must include a timezone")
        receipts[entry["profile_name"]] = entry
    return receipts


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True)
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=4)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run_probe(args: argparse.Namespace, profiles: list[Profile], home: Path, repo: Path) -> int:
    names = {name for p in profiles for name in (p.name, *p.aliases)}
    expected = set(args.expected) if args.expected else {p.name for p in profiles}
    unknown = expected - names
    if unknown:
        raise ValueError(f"Expected profiles were not discovered: {', '.join(sorted(unknown))}")
    if not expected:
        raise ValueError("Expected profile set is empty")
    prompt_path = Path(args.prompt_file).resolve()
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("Prompt file is empty")
    result_path = Path(args.result_file).resolve() if args.result_file else args.log.resolve().with_name(args.log.name + f".{args.model}-{args.effort}.exec.txt")
    log_path = args.log.resolve()
    instrument(profiles, log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start_offset = log_path.stat().st_size if log_path.exists() else 0
    env = os.environ.copy()
    command = [args.codex, "exec", "-m", args.model, "-c", f"model_reasoning_effort={args.effort}", "-s", "workspace-write", "-C", str(repo), "--add-dir", str(log_path.parent), "--ephemeral", "-o", str(result_path), prompt]
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    status = "failed"
    missing: set[str] = set(expected)
    try:
        with result_path.with_suffix(result_path.suffix + ".stdout").open("wb") as stdout, result_path.with_suffix(result_path.suffix + ".stderr").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=repo, env=env, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                                       start_new_session=os.name != "nt")
            while time.monotonic() - started < args.timeout:
                receipts = _read_receipts(log_path, start_offset)
                missing = expected - receipts.keys()
                if not missing:
                    _stop_process(process)
                    status = "complete"
                    break
                if process.poll() is not None:
                    status = "exec_exited_before_receipts"
                    break
                time.sleep(0.25)
            else:
                status = "timeout"
                _stop_process(process)
        exit_code = process.wait(timeout=10) if process.poll() is None else process.returncode
        if status == "complete":
            print(json.dumps({"status": status, "expected": sorted(expected), "receipts": sorted(expected - missing), "exec_exit_code_after_stop": exit_code}))
            return 0
        print(json.dumps({"status": status, "missing": sorted(missing), "receipts": sorted(expected - missing), "exec_exit_code": exit_code, "result_file": str(result_path)}))
        return 1
    finally:
        if process is not None and process.poll() is None:
            _stop_process(process)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        if not args.keep_instrumented:
            uninstrument(log_path)


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    home_value = args.home or os.environ.get("CODEX_HOME")
    home = Path(home_value).expanduser() if home_value else Path.home() / ".codex"
    repo = Path(args.repo).expanduser().resolve()
    return home.resolve(), repo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("discover", "instrument", "uninstrument", "run"):
        child = subs.add_parser(command)
        child.add_argument("--repo", required=True, help="Repository root")
        child.add_argument("--home", help="Codex home (defaults to CODEX_HOME or ~/.codex)")
        if command in ("instrument", "uninstrument", "run"):
            child.add_argument("--log", required=True, type=Path, help="JSONL receipt path")
        if command == "run":
            child.add_argument("--prompt-file", required=True)
            child.add_argument("--expected", action="append", help="Expected profile name; repeatable (defaults to all discovered profiles)")
            child.add_argument("--timeout", type=int, default=600, help="Maximum seconds before terminating codex exec")
            child.add_argument("--result-file")
            child.add_argument("--codex", default="codex")
            child.add_argument("--model", choices=("gpt-6-luna", "gpt-6-sol"), default="gpt-6-luna")
            child.add_argument("--effort", choices=("low", "medium", "high"), default="medium")
            child.add_argument("--keep-instrumented", action="store_true", help="Leave profile edits in place after the run")
    args = parser.parse_args(argv)
    try:
        if args.command == "run" and args.home is not None:
            raise ValueError("run uses the inherited CODEX_HOME (or ~/.codex); omit --home so discovery matches codex exec")
        if args.command == "uninstrument":
            print(json.dumps(uninstrument(args.log), indent=2))
            return 0
        home, repo = _paths(args)
        profiles = discover(home, repo)
        if args.command == "discover":
            print(json.dumps([{"name": p.name, "path": str(p.path), "sources": p.sources, "aliases": p.aliases} for p in profiles], indent=2))
            return 0
        if args.command == "instrument":
            print(json.dumps(instrument(profiles, args.log), indent=2))
            return 0
        if args.timeout < 1:
            raise ValueError("Timeout must be positive")
        return run_probe(args, profiles, home, repo)
    except (OSError, ValueError, tomllib.TOMLDecodeError, subprocess.SubprocessError) as exc:
        print(f"profile_probe: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
