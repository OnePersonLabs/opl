#!/usr/bin/env python3
"""Check and reconcile OPL-managed Codex configuration."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib
from typing import Any


sys.dont_write_bytecode = True

IGNORE_MARKER = "# opl:ignore-config-check"
IGNORE_MARKER_LINE = re.compile(r"[ \t]*#[ \t]*opl:ignore-config-check(?:[ \t]+version=([^\s#]+))?[ \t]*(?:\r?\n)?")
SCHEMA_COMMENT = re.compile(r"^[ \t]*#:[ \t]*schema\b")
EFFECTIVE_TRUE_DEFAULTS = {"features": {"hooks", "plugins", "multi_agent"}, "agents": {"enabled"}}
ROLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


class ConfigCheckError(ValueError):
    """A configuration issue that must not result in a partial repair."""


def default_home() -> Path:
    value = os.environ.get("CODEX_HOME")
    return Path(value).expanduser() if value else Path.home() / ".codex"


def default_plugin_root() -> Path:
    return Path(os.environ.get("PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)


def load_application(plugin_root: Path):
    path = plugin_root / "skills" / "configure-harness" / "scripts" / "application.py"
    if not path.is_file():
        raise ConfigCheckError(f"OPL configuration transaction helper is missing: {path}")
    spec = importlib.util.spec_from_file_location("opl_harness_application", path)
    if spec is None or spec.loader is None:
        raise ConfigCheckError(f"Cannot load OPL configuration transaction helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plugin_version(plugin_root: Path) -> str:
    path = plugin_root / ".codex-plugin" / "plugin.json"
    try:
        if not path.is_file() or path.is_symlink():
            raise ConfigCheckError(f"OPL plugin manifest is missing or unsafe: {path}")
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigCheckError(f"Cannot read OPL plugin manifest: {error}") from error
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ConfigCheckError(f"OPL plugin manifest has no usable version: {path}")
    return version


def load_defaults(plugin_root: Path) -> dict[str, dict[str, Any]]:
    path = plugin_root / "config.defaults.toml"
    try:
        if not path.is_file() or path.is_symlink():
            raise ConfigCheckError(f"OPL configuration defaults are missing or unsafe: {path}")
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigCheckError(f"Cannot read OPL configuration defaults: {error}") from error
    if not isinstance(data, dict):
        raise ConfigCheckError("OPL configuration defaults must be a TOML table")
    result: dict[str, dict[str, Any]] = {}
    for section in ("features", "agents"):
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ConfigCheckError(f"OPL configuration defaults {section} must be a table")
        checked: dict[str, Any] = {}
        for key, value in values.items():
            if not isinstance(key, str) or not ROLE_NAME.fullmatch(key):
                raise ConfigCheckError(f"OPL configuration defaults {section} has an invalid setting name")
            if not isinstance(value, (str, bool, int)):
                raise ConfigCheckError(f"OPL configuration defaults {section}.{key} must be a string, boolean, or integer")
            checked[key] = value
        result[section] = checked
    return result


def _top_marker_span(text: str) -> tuple[int, int, str | None] | None:
    lines = text.splitlines(keepends=True)
    offset = 0
    index = 0
    while index < len(lines) and SCHEMA_COMMENT.match(lines[index]):
        offset += len(lines[index])
        index += 1
    if index >= len(lines):
        return None
    line = lines[index]
    marker = IGNORE_MARKER_LINE.fullmatch(line)
    if marker is None:
        return None
    return offset, offset + len(line), marker.group(1)


def marker_state(data: bytes, version: str) -> tuple[bool, list[str | None]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as error:
        raise ConfigCheckError("config.toml is not valid UTF-8") from error
    marker = _top_marker_span(text)
    if marker is None:
        return False, []
    marker_version = marker[2]
    return marker_version == version, [] if marker_version == version else [marker_version]


def remove_stale_markers(data: bytes, version: str) -> bytes:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as error:
        raise ConfigCheckError("config.toml is not valid UTF-8") from error
    _matching, stale = marker_state(data, version)
    if not stale:
        return data
    marker = _top_marker_span(text)
    assert marker is not None
    cleaned = text[:marker[0]] + text[marker[1]:]
    return cleaned.encode("utf-8-sig") if data.startswith(b"\xef\xbb\xbf") else cleaned.encode("utf-8")


def insert_ignore_marker(data: bytes, version: str) -> bytes:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as error:
        raise ConfigCheckError("config.toml is not valid UTF-8") from error
    lines = text.splitlines(keepends=True)
    offset = 0
    for line in lines:
        if not SCHEMA_COMMENT.match(line):
            break
        offset += len(line)
    line_ending = "\r\n" if "\r\n" in text else "\n"
    prefix = text[:offset]
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += line_ending
    marker = f"{IGNORE_MARKER} version={version}{line_ending}"
    rendered = prefix + marker + text[offset:]
    return rendered.encode("utf-8-sig") if data.startswith(b"\xef\xbb\xbf") else rendered.encode("utf-8")


def read_config_bytes(home: Path) -> bytes | None:
    path = home / "config.toml"
    try:
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise ConfigCheckError(f"config.toml must be a regular file: {path}")
        return path.read_bytes()
    except OSError as error:
        raise ConfigCheckError(f"Cannot read config.toml: {error}") from error


def parse_config(data: bytes) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(data.decode("utf-8-sig"))
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigCheckError(f"config.toml is not valid TOML: {error}") from error
    if not isinstance(parsed, dict):
        raise ConfigCheckError("config.toml must contain a TOML table")
    return parsed


def role_name(path: Path) -> str:
    stem = path.stem
    name = stem if stem.startswith("opl-") else f"opl-{stem}"
    if not ROLE_NAME.fullmatch(name):
        raise ConfigCheckError(f"{path.name}: role filename must use letters, numbers, underscores, or hyphens")
    return name


def discover_agents(plugin_root: Path) -> dict[str, str]:
    root = plugin_root.resolve()
    directory = root / "agents"
    if not directory.is_dir() or directory.is_symlink():
        raise ConfigCheckError(f"OPL agents directory is missing or unsafe: {directory}")
    result: dict[str, str] = {}
    try:
        paths = sorted(directory.iterdir(), key=lambda path: path.name.casefold())
    except OSError as error:
        raise ConfigCheckError(f"Cannot read OPL agents directory: {error}") from error
    for path in paths:
        if path.suffix.casefold() != ".toml":
            continue
        if not path.is_file() or path.is_symlink():
            raise ConfigCheckError(f"OPL agent configuration must be a regular file: {path}")
        name = role_name(path)
        if name in result:
            raise ConfigCheckError(f"OPL agent files produce duplicate role name {name!r}")
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise ConfigCheckError(f"{path}: invalid TOML: {error}") from error
        if not isinstance(data, dict):
            raise ConfigCheckError(f"{path}: agent configuration must be a TOML table")
        if "name" in data:
            configured_name = data["name"]
            if not isinstance(configured_name, str) or not configured_name.strip():
                raise ConfigCheckError(f"{path}: name must be a nonempty string when provided")
            if configured_name != name:
                raise ConfigCheckError(f"{path}: name must equal {name!r}")
        if not isinstance(data.get("description"), str) or not data["description"].strip():
            raise ConfigCheckError(f"{path}: description must be a nonempty string")
        if not isinstance(data.get("developer_instructions"), str) or not data["developer_instructions"].strip():
            raise ConfigCheckError(f"{path}: developer_instructions must be a nonempty string")
        for key in ("model", "model_reasoning_effort"):
            if key in data and not isinstance(data[key], str):
                raise ConfigCheckError(f"{path}: {key} must be a string")
        result[name] = str(path.resolve())
    return result


def _table(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigCheckError(f"{name} must be a table")
    return value


def _same_scalar(left: Any, right: Any) -> bool:
    """Return true only when TOML scalar values have the same type and value."""
    return type(left) is type(right) and left == right


def _value_findings(section: str, expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for key, value in expected.items():
        observed = actual.get(key)
        if observed is None and value is True and key in EFFECTIVE_TRUE_DEFAULTS.get(section, set()):
            continue
        if not _same_scalar(observed, value):
            findings.append({
                "code": "setting_mismatch",
                "path": f"{section}.{key}",
                "expected": value,
                "actual": observed,
            })
    return findings


def evaluate(config: dict[str, Any], inventory: dict[str, str], defaults: dict[str, dict[str, Any]], *,
             include_policy: bool = True) -> dict[str, Any]:
    features = _table(config.get("features"), "features")
    agents = _table(config.get("agents"), "agents")
    findings: list[dict[str, Any]] = []
    if include_policy:
        findings.extend(_value_findings("features", defaults["features"], features))
        findings.extend(_value_findings("agents", defaults["agents"], agents))
    registered = {name: value for name, value in agents.items()
                  if isinstance(name, str) and name.startswith("opl-")}
    for name, path in inventory.items():
        current = registered.get(name)
        if current is None:
            findings.append({"code": "agent_missing", "path": f"agents.{name}", "expected": path, "actual": None})
        elif not isinstance(current, dict) or current.get("config_file") != path:
            findings.append({"code": "agent_path_mismatch", "path": f"agents.{name}.config_file",
                             "expected": path,
                             "actual": current.get("config_file") if isinstance(current, dict) else current})
    for name in registered:
        if name not in inventory:
            findings.append({"code": "agent_stale", "path": f"agents.{name}", "expected": None,
                             "actual": registered[name].get("config_file") if isinstance(registered[name], dict) else registered[name]})
    findings.sort(key=lambda item: (item["path"], item["code"]))
    return {"ignored": False, "compliant": not findings, "findings": findings,
            "agents": dict(sorted(inventory.items()))}


def _header_path(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("["):
        return None
    if stripped.startswith("[["):
        return None
    probe = "__opl_probe__"
    try:
        parsed = tomllib.loads(f"{line.rstrip()}\n{probe} = true\n")
    except tomllib.TOMLDecodeError:
        return None
    path: list[str] = []
    current: Any = parsed
    while isinstance(current, dict) and len(current) == 1:
        key, current = next(iter(current.items()))
        if key == probe:
            return tuple(path)
        path.append(key)
    return None


def table_blocks(text: str) -> list[tuple[tuple[str, ...] | None, int, int, int]]:
    """Return table path, header start, body start, and table end offsets."""
    lines = text.splitlines(keepends=True)
    starts: list[tuple[tuple[str, ...] | None, int, int]] = []
    offset = 0
    for line in lines:
        if line.lstrip().startswith("["):
            starts.append((_header_path(line), offset, offset + len(line)))
        offset += len(line)
    return [(path, start, body, starts[index + 1][1] if index + 1 < len(starts) else len(text))
            for index, (path, start, body) in enumerate(starts)]


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    raise ConfigCheckError("OPL configuration defaults contain an unsupported scalar value")


def _line_ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _replace_values(body: str, values: dict[str, Any], line_ending: str) -> str:
    for key, value in values.items():
        pattern = re.compile(rf"(?m)^([ \t]*{re.escape(key)}[ \t]*=[ \t]*)([^#\r\n]*)([ \t]*(?:#.*)?)(\r?\n|$)")
        matches = list(pattern.finditer(body))
        if len(matches) > 1:
            raise ConfigCheckError(f"Duplicate {key} assignment in managed TOML table")
        rendered = _toml_scalar(value)
        if matches:
            match = matches[0]
            ending = match.group(4) or line_ending
            comment = match.group(3)
            if comment.startswith("#"):
                comment = " " + comment
            body = body[:match.start()] + match.group(1) + rendered + comment + ending + body[match.end():]
        else:
            prefix = "" if not body or body.endswith(("\n", "\r")) else line_ending
            body = prefix + f"{key} = {rendered}{line_ending}" + body
    return body


def _insert_table(text: str, path: tuple[str, ...], values: dict[str, Any]) -> str:
    line_ending = _line_ending(text)
    header = "[" + ".".join(_quote(part) if not ROLE_NAME.fullmatch(part) else part for part in path) + "]"
    body = "".join(f"{key} = {_toml_scalar(value)}{line_ending}"
                   for key, value in values.items())
    insertion = header + line_ending + body
    blocks = table_blocks(text)
    children = [start for current, start, _body, _end in blocks if current and current[:len(path)] == path]
    if children:
        position = min(children)
        return text[:position] + insertion + line_ending + text[position:]
    separator = "" if not text or text.endswith(("\n", "\r")) else line_ending
    if text and not text.endswith(("\n\n", "\r\n\r\n")):
        separator += line_ending
    return text + separator + insertion


def _update_table_values(text: str, path: tuple[str, ...], values: dict[str, Any]) -> str:
    if not values:
        return text
    blocks = [item for item in table_blocks(text) if item[0] == path]
    if len(blocks) > 1:
        raise ConfigCheckError(f"Duplicate TOML table {'.'.join(path)}")
    if not blocks:
        return _insert_table(text, path, values)
    _current, _start, body_start, end = blocks[0]
    body = text[body_start:end]
    replacement = _replace_values(body, values, _line_ending(text))
    return text[:body_start] + replacement + text[end:]


def _remove_table(text: str, path: tuple[str, ...]) -> str:
    blocks = [item for item in table_blocks(text) if item[0] == path]
    if len(blocks) > 1:
        raise ConfigCheckError(f"Duplicate TOML table {'.'.join(path)}")
    if not blocks:
        raise ConfigCheckError(f"Cannot remove {'.'.join(path)} because it is not a TOML table")
    _current, start, _body, end = blocks[0]
    body = text[start:end]
    lines = body.splitlines(keepends=True)
    preserved: list[str] = []
    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith("#")):
        preserved.insert(0, lines.pop())
    return text[:start] + "".join(preserved) + text[end:]


def render_config(original: bytes, config: dict[str, Any], inventory: dict[str, str], defaults: dict[str, dict[str, Any]], *,
                  include_policy: bool) -> bytes:
    try:
        text = original.decode("utf-8-sig")
    except UnicodeError as error:
        raise ConfigCheckError("config.toml is not valid UTF-8") from error
    if include_policy:
        text = _update_table_values(text, ("features",), defaults["features"])
        text = _update_table_values(text, ("agents",), defaults["agents"])

    agents = _table(config.get("agents"), "agents")
    current = {name: value for name, value in agents.items()
               if isinstance(name, str) and name.startswith("opl-")}
    for name in sorted(current):
        if name not in inventory:
            text = _remove_table(text, ("agents", name))
    for name, path in sorted(inventory.items()):
        existing = current.get(name)
        if existing is None:
            text = _insert_table(text, ("agents", name), {"config_file": path})
        elif not isinstance(existing, dict):
            raise ConfigCheckError(f"agents.{name} must be a TOML table before it can be updated")
        elif existing.get("config_file") != path:
            text = _update_table_values(text, ("agents", name), {"config_file": path})
    return text.encode("utf-8-sig") if original.startswith(b"\xef\xbb\xbf") else text.encode("utf-8")


def _verify_rendered(data: bytes, inventory: dict[str, str], defaults: dict[str, dict[str, Any]], *,
                     include_policy: bool) -> None:
    report = evaluate(parse_config(data), inventory, defaults, include_policy=include_policy)
    if not report["compliant"]:
        paths = ", ".join(finding["path"] for finding in report["findings"])
        raise ConfigCheckError(f"Rendered config.toml does not satisfy the requested OPL state: {paths}")


def _candidate(home: Path, data: bytes) -> Path:
    directory = home / "opl" / "harness" / "candidates"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".config-check-", suffix=".toml", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        os.close(descriptor)
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def apply_config(home: Path, plugin_root: Path, original: bytes | None, candidate_data: bytes) -> dict[str, Any]:
    application = load_application(plugin_root)
    candidate = _candidate(home, candidate_data)
    try:
        plan = application.prepare(home, [{"target": str(home / "config.toml"), "candidate": str(candidate)}])
        expected_hash = application.MISSING if original is None else hashlib.sha256(original).hexdigest()
        if plan["files"][0]["original_sha256"] != expected_hash:
            raise ConfigCheckError("config.toml changed while OPL prepared its repair; inspect it again before retrying")
        return application.apply(home, plan)
    finally:
        candidate.unlink(missing_ok=True)


def apply_verified_config(home: Path, plugin_root: Path, original: bytes | None, candidate: bytes,
                          inventory: dict[str, str], defaults: dict[str, dict[str, Any]], *, include_policy: bool) -> dict[str, Any]:
    _verify_rendered(candidate, inventory, defaults, include_policy=include_policy)
    result = apply_config(home, plugin_root, original, candidate)
    final = read_config_bytes(home)
    if final is None:
        raise ConfigCheckError("config.toml disappeared after OPL applied its repair")
    _verify_rendered(final, inventory, defaults, include_policy=include_policy)
    return result


def _normalize_stale_markers(home: Path, plugin_root: Path, original: bytes | None, version: str) -> tuple[bytes | None, list[str | None]]:
    raw = original or b""
    _matching, stale = marker_state(raw, version)
    if not stale:
        return original, []
    candidate = remove_stale_markers(raw, version)
    apply_config(home, plugin_root, original, candidate)
    current = read_config_bytes(home)
    if current is None:
        raise ConfigCheckError("config.toml disappeared after stale ignore markers were removed")
    return current, stale


def inspect(home: Path, plugin_root: Path, *, include_policy: bool = True,
            respect_ignore_marker: bool = True) -> tuple[bytes | None, dict[str, Any], dict[str, str], dict[str, dict[str, Any]], dict[str, Any]]:
    version = plugin_version(plugin_root)
    original = read_config_bytes(home)
    original, removed_markers = _normalize_stale_markers(home, plugin_root, original, version)
    raw = original or b""
    matching_marker, _stale = marker_state(raw, version)
    if respect_ignore_marker and matching_marker:
        return original, {}, {}, {}, {"ignored": True, "compliant": True, "findings": [], "agents": {}, "version": version}
    defaults = load_defaults(plugin_root)
    config = parse_config(raw)
    inventory = discover_agents(plugin_root)
    report = evaluate(config, inventory, defaults, include_policy=include_policy)
    report["version"] = version
    if removed_markers:
        report["removed_ignore_markers"] = removed_markers
    return original, config, inventory, defaults, report


def command_check(home: Path, plugin_root: Path) -> tuple[dict[str, Any], int]:
    _original, _config, _inventory, _defaults, report = inspect(home, plugin_root)
    return report, 0 if report["compliant"] else 1


def command_reconcile(home: Path, plugin_root: Path) -> tuple[dict[str, Any], int]:
    original, config, inventory, defaults, report = inspect(home, plugin_root, include_policy=False, respect_ignore_marker=False)
    if report["compliant"]:
        return report, 0
    candidate = render_config(original or b"", config, inventory, defaults, include_policy=False)
    result = apply_verified_config(home, plugin_root, original, candidate, inventory, defaults, include_policy=False)
    return {**report, "applied": result}, 0


def command_fix(home: Path, plugin_root: Path) -> tuple[dict[str, Any], int]:
    original, config, inventory, defaults, report = inspect(home, plugin_root, respect_ignore_marker=False)
    if report["compliant"]:
        return report, 0
    candidate = render_config(original or b"", config, inventory, defaults, include_policy=True)
    result = apply_verified_config(home, plugin_root, original, candidate, inventory, defaults, include_policy=True)
    return {**report, "applied": result}, 0


def command_ignore(home: Path, plugin_root: Path) -> tuple[dict[str, Any], int]:
    version = plugin_version(plugin_root)
    original = read_config_bytes(home)
    original, _removed_markers = _normalize_stale_markers(home, plugin_root, original, version)
    raw = original or b""
    matching_marker, _stale = marker_state(raw, version)
    if matching_marker:
        return {"ignored": True, "compliant": True, "findings": [], "version": version}, 0
    result = apply_config(home, plugin_root, original, insert_ignore_marker(raw, version))
    return {"ignored": True, "compliant": True, "findings": [], "version": version, "applied": result}, 0


def is_subagent(payload: dict[str, Any]) -> bool:
    return bool(payload.get("agent_id") or payload.get("is_subagent") or payload.get("source") == "subagent")


def _finding_text(finding: dict[str, Any]) -> str:
    expected = finding.get("expected")
    actual = finding.get("actual")
    return f"{finding['path']}: {actual!r} -> {expected!r}"


def command_hook(home: Path, plugin_root: Path) -> tuple[dict[str, Any], int]:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as error:
        raise ConfigCheckError(f"invalid hook input: {error}") from error
    if not isinstance(payload, dict):
        raise ConfigCheckError("hook input must be a JSON object")
    event = payload.get("hook_event_name", "SessionStart")
    if event != "SessionStart":
        raise ConfigCheckError(f"unsupported hook event: {event}")
    if is_subagent(payload):
        return {"suppressed": True}, 0
    try:
        report, _status = command_check(home, plugin_root)
    except ConfigCheckError as error:
        message = f"OPL configuration check could not inspect config.toml: {error}"
        return {"systemMessage": message, "hookSpecificOutput": {"hookEventName": event,
                "additionalContext": message + " Tell the user. Do not attempt an automatic repair of invalid TOML. They may repair it manually or choose the versioned OPL configuration-check ignore marker to suppress this check."}}, 0
    if report["compliant"]:
        return {}, 0
    summary = "OPL configuration needs attention: " + "; ".join(_finding_text(finding) for finding in report["findings"])
    context = (summary + ". Tell the user the proposed OPL configuration changes, ask whether to fix them or add "
               f"{IGNORE_MARKER} version={report['version']}, and pause before starting their task. Keep the original task in conversation.")
    return {"systemMessage": summary,
            "hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "fix", "ignore", "reconcile", "hook"))
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("--plugin-root", type=Path, default=default_plugin_root())
    args = parser.parse_args(argv)
    home = args.home.expanduser().resolve()
    plugin_root = args.plugin_root.expanduser().resolve()
    if args.command == "check":
        report, status = command_check(home, plugin_root)
    elif args.command == "fix":
        report, status = command_fix(home, plugin_root)
    elif args.command == "ignore":
        report, status = command_ignore(home, plugin_root)
    elif args.command == "reconcile":
        report, status = command_reconcile(home, plugin_root)
    else:
        report, status = command_hook(home, plugin_root)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return status


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigCheckError, OSError, ValueError) as error:
        print(f"codex-config-check: {error}", file=sys.stderr)
        raise SystemExit(2)
