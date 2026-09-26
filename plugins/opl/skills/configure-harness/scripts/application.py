#!/usr/bin/env python3
"""Apply reviewed global harness files with conflict detection and recovery."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import tomllib
import uuid


MISSING = "missing"
MANAGED_HEADING = "## Harness Policies (managed by $opl:configure-harness)"
_HEADING = re.compile(r"^#{1,2} (?!#)", re.MULTILINE)
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_IGNORE_CONFIG_MARKER = re.compile(r"[ \t]*#[ \t]*opl:ignore-config-check(?:[ \t]+version=[^\s#]+)?[ \t]*(?:\r?\n)?")
_SCHEMA_COMMENT = re.compile(r"^[ \t]*#:[ \t]*schema\b")


def _hash(data: bytes | None) -> str:
    return MISSING if data is None else hashlib.sha256(data).hexdigest()


def _absolute(path: str | Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("paths must be absolute")
    return path


def _home(home: Path) -> Path:
    path = _absolute(home)
    if not path.is_dir() or path.is_symlink():
        raise ValueError("home must be an existing, non-symlink directory")
    return path.resolve(strict=True)


def _no_links(path: Path, root: Path) -> None:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise ValueError("path is outside home") from None
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("symlink traversal is forbidden")


def _no_any_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("symlink traversal is forbidden")


def _effective_instructions(home: Path) -> Path:
    override = home / "AGENTS.override.md"
    _no_links(override, home)
    if override.is_file() and override.read_bytes().strip():
        return override
    return home / "AGENTS.md"


def _target_kind(home: Path, target: Path) -> str:
    if target != _absolute(target):
        raise ValueError("target must be absolute")
    _no_links(target, home)
    if target == _effective_instructions(home):
        return "instructions"
    if target == home / "config.toml":
        return "config"
    policy_dir = home / "opl" / "harness" / "policies"
    if target.parent == policy_dir and target.suffix == ".md" and target.name not in (".", ".."):
        return "policy"
    raise ValueError("target is outside permitted global harness files")


def _read_regular(path: Path) -> bytes | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ValueError("expected a regular, non-symlink file")
    return path.read_bytes()


def _without_managed(data: bytes | None) -> str:
    if data is None:
        return ""
    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == MANAGED_HEADING]
    if len(matches) > 1:
        raise ValueError("duplicate managed policy section")
    if not matches:
        return text
    start = matches[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _HEADING.match(lines[index]):
            end = index
            break
    return "".join(lines[:start] + lines[end:])


def _validate_instructions(before: bytes | None, after: bytes) -> None:
    old_outside = _without_managed(before)
    new_outside = _without_managed(after)
    if old_outside == new_outside:
        return
    old_lines = old_outside.splitlines()
    new_lines = after.decode("utf-8").splitlines()
    first_section = MANAGED_HEADING not in old_lines and MANAGED_HEADING in new_lines
    if first_section and old_outside and not old_outside.endswith(("\r", "\n")):
        if new_outside in (old_outside + "\n", old_outside + "\r\n"):
            return
    raise ValueError("AGENTS.md changes outside the managed policy section")


def _validate_config(before: bytes | None, after: bytes) -> None:
    # The config checker must be able to acknowledge itself even when an
    # unrelated malformed TOML file prevents normal configuration validation.
    # This is deliberately an append-only byte transition.
    if _is_ignore_config_marker_change(before, after):
        return
    try:
        old = tomllib.loads((before or b"").decode("utf-8-sig"))
        new = tomllib.loads(after.decode("utf-8-sig"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("config.toml must contain valid UTF-8 TOML") from exc
    old_rest, new_rest = copy.deepcopy(old), copy.deepcopy(new)

    for section in ("plugins", "mcp_servers"):
        original = old.get(section, {})
        proposed = new.get(section, {})
        if not isinstance(original, dict) or not isinstance(proposed, dict):
            raise ValueError(f"{section} must be a table")
        for name, entry in proposed.items():
            if not isinstance(entry, dict):
                raise ValueError(f"{section} entries must be tables")
            if name not in original:
                if section == "mcp_servers" or set(entry) != {"enabled"}:
                    raise ValueError("new MCP definitions or plugin settings are forbidden")
            if "enabled" in entry and not isinstance(entry["enabled"], bool):
                raise ValueError("enabled must be a boolean")
            new_rest[section][name].pop("enabled", None)
            if name not in original:
                del new_rest[section][name]
        for name, entry in original.items():
            if not isinstance(entry, dict):
                raise ValueError(f"{section} entries must be tables")
            old_rest[section][name].pop("enabled", None)
        if section in new_rest and not new_rest[section] and section not in old_rest:
            del new_rest[section]

    original_skills = old.get("skills", {})
    proposed_skills = new.get("skills", {})
    if not isinstance(original_skills, dict) or not isinstance(proposed_skills, dict):
        raise ValueError("skills must be a table")
    old_entries = original_skills.get("config", [])
    new_entries = proposed_skills.get("config", [])
    if not isinstance(old_entries, list) or not isinstance(new_entries, list):
        raise ValueError("skills.config must be an array of tables")
    def indexed(entries: list) -> dict[str, dict]:
        result = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("skills.config entries require a path")
            path = entry["path"]
            if path in result:
                raise ValueError("duplicate skills.config path")
            result[path] = entry
        return result
    original_by_path = indexed(old_entries)
    proposed_by_path = indexed(new_entries)
    if not set(original_by_path).issubset(proposed_by_path):
        raise ValueError("existing skills.config entries cannot be removed")
    for path, entry in proposed_by_path.items():
        if "enabled" in entry and not isinstance(entry["enabled"], bool):
            raise ValueError("skills.config enabled must be a boolean")
        if path not in original_by_path:
            if set(entry) != {"path", "enabled"}:
                raise ValueError("new skills.config entries may only set path and enabled")
        elif "enabled" in original_by_path[path] and "enabled" not in entry:
            raise ValueError("existing skills.config enabled cannot be removed")
        if path in original_by_path:
            without_enabled = {key: value for key, value in entry.items() if key != "enabled"}
            prior = {key: value for key, value in original_by_path[path].items() if key != "enabled"}
            if without_enabled != prior:
                raise ValueError("other skills.config settings cannot change")
    if "skills" in old_rest:
        old_rest["skills"].pop("config", None)
    if "skills" in new_rest:
        new_rest["skills"].pop("config", None)
        if not new_rest["skills"] and "skills" not in old_rest:
            del new_rest["skills"]

    _validate_config_checker_policy(old, new, old_rest, new_rest)
    if old_rest != new_rest:
        raise ValueError("config.toml changes outside allowed OPL configuration settings")


def _is_ignore_config_marker_change(before: bytes | None, after: bytes) -> bool:
    """Allow only a top insertion or removal of standalone config-check markers."""
    try:
        original = (before or b"").decode("utf-8-sig")
        candidate = after.decode("utf-8-sig")
    except UnicodeError:
        return False
    marker = _top_ignore_config_marker(original)
    if marker is not None and candidate == original[:marker[0]] + original[marker[1]:]:
        return True
    if marker is not None:
        return False
    marker = _top_ignore_config_marker(candidate)
    if marker is None:
        return False
    line = candidate[marker[0]:marker[1]]
    if "version=" not in line:
        return False
    return candidate[:marker[0]] + candidate[marker[1]:] == original


def _top_ignore_config_marker(text: str) -> tuple[int, int] | None:
    lines = text.splitlines(keepends=True)
    offset = 0
    index = 0
    while index < len(lines) and _SCHEMA_COMMENT.match(lines[index]):
        offset += len(lines[index])
        index += 1
    if index >= len(lines) or _IGNORE_CONFIG_MARKER.fullmatch(lines[index]) is None:
        return None
    return offset, offset + len(lines[index])


def _insert_ignore_config_marker(text: str, marker: str) -> str:
    lines = text.splitlines(keepends=True)
    offset = 0
    for line in lines:
        if not _SCHEMA_COMMENT.match(line):
            break
        offset += len(line)
    line_ending = "\r\n" if "\r\n" in text else "\n"
    prefix = text[:offset]
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += line_ending
    return prefix + marker.rstrip("\r\n") + line_ending + text[offset:]


def _validate_config_checker_policy(old: dict, new: dict, old_rest: dict, new_rest: dict) -> None:
    """Permit the narrow policy managed by OPL's configuration checker."""
    defaults = _load_config_defaults()
    _validate_policy_section("features", old, new, old_rest, new_rest, defaults["features"])
    _validate_policy_section("agents", old, new, old_rest, new_rest, defaults["agents"])


def _table(value, name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a table")
    return value


def _discard(rest: dict, section: str, key: str) -> None:
    table = rest.get(section)
    if isinstance(table, dict):
        table.pop(key, None)
        if not table:
            rest.pop(section, None)


def _same_scalar(left, right) -> bool:
    """Return true only when TOML scalar values have the same type and value."""
    return type(left) is type(right) and left == right


def _validate_policy_section(section: str, old: dict, new: dict, old_rest: dict, new_rest: dict,
                             defaults: dict) -> None:
    original = _table(old.get(section), section)
    proposed = _table(new.get(section), section)
    for key, expected in defaults.items():
        prior = original.get(key)
        value = proposed.get(key)
        if not _same_scalar(value, prior) and not _same_scalar(value, expected):
            raise ValueError(f"{section}.{key} must be {expected!r} when changed")
        _discard(old_rest, section, key)
        _discard(new_rest, section, key)

    if section != "agents":
        return

    names = {key for key in original if isinstance(key, str) and key.startswith("opl-")}
    names.update(key for key in proposed if isinstance(key, str) and key.startswith("opl-"))
    for name in names:
        prior = original.get(name)
        value = proposed.get(name)
        if value is not None:
            if not isinstance(value, dict) or not isinstance(value.get("config_file"), str):
                raise ValueError(f"agents.{name} requires a string config_file")
            if prior is None and set(value) != {"config_file"}:
                raise ValueError(f"new agents.{name} entries may only set config_file")
            if prior is not None:
                if not isinstance(prior, dict):
                    raise ValueError(f"agents.{name} must be a table")
                old_extra = {key: item for key, item in prior.items() if key != "config_file"}
                new_extra = {key: item for key, item in value.items() if key != "config_file"}
                if old_extra != new_extra:
                    raise ValueError(f"agents.{name} settings other than config_file cannot change")
        _discard(old_rest, "agents", name)
        _discard(new_rest, "agents", name)


def _load_config_defaults() -> dict[str, dict]:
    path = Path(__file__).resolve().parents[3] / "config.defaults.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"OPL config defaults are invalid: {exc}") from exc
    result = {}
    for section in ("features", "agents"):
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"OPL config defaults {section} must be a table")
        checked = {}
        for key, value in values.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", key):
                raise ValueError(f"OPL config defaults {section} has an invalid setting name")
            if isinstance(value, bool) or isinstance(value, (str, int)):
                checked[key] = value
            else:
                raise ValueError(f"OPL config defaults {section}.{key} must be a string, boolean, or integer")
        result[section] = checked
    return result


def _validate(kind: str, before: bytes | None, after: bytes) -> None:
    if kind == "instructions":
        _validate_instructions(before, after)
    elif kind == "config":
        _validate_config(before, after)
    else:
        after.decode("utf-8")


def prepare(home: Path, files: list[dict]) -> dict:
    """Bind candidate bytes and reviewed target snapshots without writing files."""
    root = _home(home)
    if not isinstance(files, list) or not files:
        raise ValueError("files must be a nonempty list")
    entries, seen = [], set()
    candidates = set()
    for item in files:
        target, candidate = _absolute(item["target"]), _absolute(item["candidate"])
        kind = _target_kind(root, target)
        if target in seen or target == candidate:
            raise ValueError("duplicate target or candidate equal to target")
        seen.add(target)
        _no_any_links(candidate)
        candidates.add(candidate)
        original = _read_regular(target)
        replacement = _read_regular(candidate)
        if replacement is None:
            raise ValueError("candidate file is missing")
        _validate(kind, original, replacement)
        entries.append({"target": str(target), "candidate": str(candidate), "kind": kind,
                        "original_sha256": _hash(original), "candidate_sha256": _hash(replacement)})
    if seen & candidates:
        raise ValueError("a candidate cannot also be a target")
    return {"home": str(root), "files": entries}


def _check_plan(root: Path, plan: dict) -> list[tuple[dict, bytes | None, bytes]]:
    if plan.get("home") != str(root) or not isinstance(plan.get("files"), list) or not plan["files"]:
        raise ValueError("invalid or mismatched application plan")
    checked, seen, candidates = [], set(), set()
    for entry in plan["files"]:
        target, candidate = _absolute(entry["target"]), _absolute(entry["candidate"])
        kind = _target_kind(root, target)
        if target in seen or target == candidate or kind != entry.get("kind"):
            raise ValueError("invalid or duplicate plan target")
        seen.add(target)
        _no_any_links(candidate)
        candidates.add(candidate)
        original, replacement = _read_regular(target), _read_regular(candidate)
        if _hash(original) != entry.get("original_sha256"):
            raise ValueError("target changed since review")
        if replacement is None or _hash(replacement) != entry.get("candidate_sha256"):
            raise ValueError("candidate changed since review")
        _validate(kind, original, replacement)
        checked.append((entry, original, replacement))
    if seen & candidates:
        raise ValueError("a candidate cannot also be a target")
    return checked


def _atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=".opl-harness-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if mode is not None:
            os.chmod(staging, stat.S_IMODE(mode))
        os.replace(staging, path)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


def _write_receipt(path: Path, receipt: dict) -> None:
    _atomic_write(path, json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8"))


def apply(home: Path, plan: dict) -> dict:
    """Apply a reviewed plan; roll back own writes if application fails."""
    root = _home(home)
    checked = _check_plan(root, plan)
    tx_root = root / "opl" / "harness" / "transactions"
    _no_links(tx_root, root)
    tx_root.mkdir(parents=True, exist_ok=True)
    tx_dir = tx_root / str(uuid.uuid4())
    tx_dir.mkdir(mode=0o700)
    receipt = {"home": str(root), "transaction": str(tx_dir), "state": "prepared", "files": []}
    for index, (entry, original, replacement) in enumerate(checked):
        backup = None
        if original is not None:
            backup = tx_dir / f"{index}.backup"
            with backup.open("xb") as file:
                file.write(original)
                file.flush()
                os.fsync(file.fileno())
        receipt["files"].append({"target": entry["target"], "kind": entry["kind"],
                                 "original_sha256": entry["original_sha256"],
                                 "candidate_sha256": entry["candidate_sha256"],
                                 "backup": str(backup) if backup else None, "status": "pending"})
    receipt_path = tx_dir / "receipt.json"
    _write_receipt(receipt_path, receipt)
    try:
        for index, (entry, original, replacement) in enumerate(checked):
            target = Path(entry["target"])
            _target_kind(root, target)
            if _hash(_read_regular(target)) != entry["original_sha256"]:
                raise ValueError("target changed during application")
            if _hash(_read_regular(Path(entry["candidate"]))) != entry["candidate_sha256"]:
                raise ValueError("candidate changed during application")
            if original == replacement:
                receipt["files"][index]["status"] = "unchanged"
            else:
                mode = target.stat().st_mode if original is not None else None
                _atomic_write(target, replacement, mode)
                receipt["files"][index]["status"] = "written"
            _write_receipt(receipt_path, receipt)
        receipt["state"] = "applied"
        _write_receipt(receipt_path, receipt)
    except (OSError, ValueError) as exc:
        try:
            rollback(root, str(receipt_path))
        except (OSError, ValueError) as rollback_error:
            raise RuntimeError("application failed and rollback has conflicts; inspect transaction receipt") from rollback_error
        raise exc
    return {"receipt": str(receipt_path), "state": "applied", "changed": sum(e["status"] == "written" for e in receipt["files"])}


def rollback(home: Path, receipt: dict | str | Path) -> dict:
    """Restore only this transaction's writes when target hashes still match."""
    root = _home(home)
    if isinstance(receipt, (str, Path)):
        receipt_path = _absolute(receipt)
        _no_links(receipt_path, root)
        record = json.loads(receipt_path.read_text(encoding="utf-8"))
    else:
        record = receipt
        receipt_path = Path(record["transaction"]) / "receipt.json"
    tx_root = root / "opl" / "harness" / "transactions"
    tx_dir = _absolute(record["transaction"])
    if tx_dir.parent != tx_root or receipt_path != tx_dir / "receipt.json":
        raise ValueError("receipt is outside harness transactions")
    _no_links(receipt_path, root)
    if record.get("home") != str(root) or not isinstance(record.get("files"), list):
        raise ValueError("invalid receipt")
    if isinstance(receipt, dict):
        persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
        if persisted != record:
            raise ValueError("receipt does not match durable transaction")
    restored = []
    conflicts = []
    for entry in record["files"]:
        target = _absolute(entry["target"])
        if _target_kind(root, target) != entry.get("kind"):
            raise ValueError("receipt target is not permitted")
        original_hash, candidate_hash = entry.get("original_sha256"), entry.get("candidate_sha256")
        if original_hash != MISSING and (not isinstance(original_hash, str) or not _DIGEST.fullmatch(original_hash)):
            raise ValueError("invalid original hash")
        if not isinstance(candidate_hash, str) or not _DIGEST.fullmatch(candidate_hash):
            raise ValueError("invalid candidate hash")
        backup = entry.get("backup")
        if original_hash == MISSING:
            if backup is not None:
                raise ValueError("unexpected backup")
            original = None
        else:
            if backup is None or Path(backup).parent != tx_dir:
                raise ValueError("backup is outside transaction")
            _no_links(Path(backup), root)
            original = _read_regular(Path(backup))
            if _hash(original) != original_hash:
                raise ValueError("backup changed")
        actual = _hash(_read_regular(target))
        if actual == original_hash:
            continue
        if actual != candidate_hash:
            conflicts.append(target)
            continue
        restored.append((target, original, candidate_hash))
    restored_count = 0
    for target, original, expected_hash in reversed(restored):
        _target_kind(root, target)
        if _hash(_read_regular(target)) != expected_hash:
            conflicts.append(target)
            continue
        if original is None:
            target.unlink()
        else:
            mode = target.stat().st_mode
            _atomic_write(target, original, mode)
        restored_count += 1
    record["state"] = "rollback_conflict" if conflicts else "rolled_back"
    _write_receipt(receipt_path, record)
    if conflicts:
        raise ValueError(f"{len(conflicts)} target(s) changed after application; conflicting files were preserved")
    return {"receipt": str(receipt_path), "state": "rolled_back", "restored": restored_count}
