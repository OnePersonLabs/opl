"""Versioned, declarative slop detector catalog.

The catalog contains data, never Python or model-generated executable code.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import sys
from typing import Any


SCHEMA_VERSION = 1
MAX_PATTERN = 300
STEERING = {
    "examine_premise": "If this applies, examine the premise and correct the response; otherwise continue.",
    "verify_claim": "If this applies, verify the claim and correct it; otherwise continue.",
    "complete_work": "If this applies, complete the outstanding work; otherwise continue.",
}
ROLES = {"assistant", "user", "tool"}
PHASES = {"user", "commentary", "final_answer"}
EVENTS = {"UserPromptSubmit", "PreToolUse", "Stop"}


class CatalogError(ValueError):
    """Catalog cannot be used safely; the operator must repair it."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Cannot read catalog file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CatalogError(f"Catalog file {path} must contain a JSON object")
    return value


def _string_list(value: Any, name: str, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise CatalogError(f"{name} must be a nonempty-string array")
    if allowed is not None and not set(value) <= allowed:
        raise CatalogError(f"{name} contains an unsupported value")
    return value


def _validate_expression(value: Any, kind: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_PATTERN:
        raise CatalogError(f"{name} must be a string of 1..{MAX_PATTERN} characters")
    if kind == "regex":
        # The stdlib regex engine has no per-match timeout. Keep the accepted
        # subset free of repetition so a hook cannot stall on backtracking.
        if re.search(r"(?<!\\)[*+?{}]", value) or re.search(r"\\[1-9]", value):
            raise CatalogError(f"{name} uses repetition or backreferences unsupported in hooks")
        try:
            re.compile(value, re.IGNORECASE)
        except re.error as exc:
            raise CatalogError(f"Invalid regex in {name}: {exc}") from exc
    return value


def validate_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"catalog.schema_version must be {SCHEMA_VERSION}")
    version = catalog.get("version")
    if type(version) is not int or version < 0:
        raise CatalogError("catalog.version must be a nonnegative integer")
    detectors = catalog.get("detectors")
    if not isinstance(detectors, list):
        raise CatalogError("catalog.detectors must be an array")
    seen: set[str] = set()
    for detector in detectors:
        if not isinstance(detector, dict):
            raise CatalogError("Each detector must be an object")
        ident = detector.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,79}", ident) or ident in seen:
            raise CatalogError("Detector IDs must be unique stable identifiers")
        seen.add(ident)
        kind = detector.get("kind")
        if kind not in {"literal", "regex"}:
            raise CatalogError(f"{ident}.kind must be literal or regex")
        _validate_expression(detector.get("pattern"), kind, f"{ident}.pattern")
        _string_list(detector.get("roles"), f"{ident}.roles", ROLES)
        _string_list(detector.get("phases"), f"{ident}.phases", PHASES)
        _string_list(detector.get("events", []), f"{ident}.events", EVENTS)
        context = detector.get("context", {})
        if not isinstance(context, dict) or set(context) - {"all", "any"}:
            raise CatalogError(f"{ident}.context must contain only all/any arrays")
        for key in ("all", "any"):
            for expression in _string_list(context.get(key, []), f"{ident}.context.{key}"):
                _validate_expression(expression, "literal", f"{ident}.context.{key}")
        for expression in _string_list(detector.get("exclude", []), f"{ident}.exclude"):
            _validate_expression(expression, "literal", f"{ident}.exclude")
        if detector.get("steering") not in STEERING:
            raise CatalogError(f"{ident}.steering must name a fixed steering template")
        evidence_ids = _string_list(detector.get("evidence_ids"), f"{ident}.evidence_ids")
        if not evidence_ids or len(evidence_ids) > 20:
            raise CatalogError(f"{ident} requires provenance evidence IDs")
    return catalog


def load_catalog(data_repo: str | Path) -> dict[str, Any]:
    path = Path(data_repo) / "catalog" / "active.json"
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "version": 0, "detectors": []}
    return validate_catalog(_read_json(path))


def match_patterns(text: str, role: str, phase: str, catalog: dict[str, Any], event: str | None = None) -> list[dict[str, Any]]:
    """Return bounded match metadata, without retaining matched source text."""
    if not isinstance(text, str) or role not in ROLES or phase not in PHASES:
        return []
    folded = text.casefold()
    matches: list[dict[str, Any]] = []
    for detector in catalog.get("detectors", []):
        if role not in detector["roles"] or phase not in detector["phases"]:
            continue
        if event and detector.get("events") and event not in detector["events"]:
            continue
        context = detector.get("context", {})
        if any(item.casefold() not in folded for item in context.get("all", [])):
            continue
        if context.get("any") and not any(item.casefold() in folded for item in context["any"]):
            continue
        if any(item.casefold() in folded for item in detector.get("exclude", [])):
            continue
        pattern = detector["pattern"]
        if detector["kind"] == "literal":
            found = pattern.casefold() in folded
        else:
            found = re.search(pattern, text, re.IGNORECASE) is not None
        if found:
            matches.append({"pattern_id": detector["id"], "catalog_version": catalog["version"],
                            "steering": detector["steering"], "evidence_ids": detector["evidence_ids"]})
    return matches


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".catalog-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _cases(data_repo: Path) -> list[dict[str, Any]]:
    path = data_repo / "catalog" / "cases.json"
    if not path.exists():
        raise CatalogError(f"Promotion requires labeled cases at {path}")
    cases = _read_json(path).get("cases")
    if not isinstance(cases, list):
        raise CatalogError("cases.json must contain a cases array")
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("text"), str):
            raise CatalogError("Each case needs text")
        if case.get("role") not in ROLES or case.get("phase") not in PHASES:
            raise CatalogError("Each case needs a supported role and phase")
        if case.get("split") not in {"discovery", "validation"} or type(case.get("expected_match")) is not bool:
            raise CatalogError("Each case needs discovery/validation split and Boolean expected_match")
        if not isinstance(case.get("evidence_id"), str) or not case["evidence_id"]:
            raise CatalogError("Each case needs an evidence_id")
        evidence_id = case["evidence_id"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", evidence_id):
            raise CatalogError("Evidence IDs must be simple filenames")
        evidence_path = data_repo / "evidence" / f"{evidence_id}.json"
        evidence = _read_json(evidence_path)
        source = evidence.get("path")
        offset = evidence.get("byte_offset")
        line = evidence.get("raw_line")
        if not isinstance(source, str) or type(offset) is not int or offset < 0 or type(line) is not int or line < 1:
            raise CatalogError(f"Case {evidence_id} has no verifiable source anchor")
        try:
            with open(source, "rb") as stream:
                stream.seek(offset)
                raw = stream.readline(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise CatalogError(f"Evidence source record too large to validate: {evidence_id}")
            record = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise CatalogError(f"Cannot verify evidence source {evidence_id}: {exc}") from exc
        reader_path = Path(__file__).resolve().parents[2] / "session-reader" / "scripts" / "session_reader.py"
        spec = importlib.util.spec_from_file_location("slop_catalog_reader", reader_path)
        if spec is None or spec.loader is None:
            raise CatalogError(f"Cannot load source reader: {reader_path}")
        reader = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = reader
        spec.loader.exec_module(reader)
        parsed = reader.parse_message(record, line, offset)
        if parsed:
            actual_role, actual_text, actual_phase = parsed[1].role, parsed[1].text, parsed[1].phase
        elif record.get("type") in {"user", "assistant"} and isinstance(record.get("message"), dict):
            actual_role = record["type"]
            actual_text = reader.text_from_content(record["message"].get("content"))
            actual_phase = "final_answer" if actual_role == "assistant" else "user"
        else:
            raise CatalogError(f"Evidence {evidence_id} is not canonical message prose")
        if actual_role != case["role"] or actual_phase != case["phase"] or evidence.get("body") != actual_text or not case["text"] or case["text"] not in actual_text:
            raise CatalogError(f"Evidence {evidence_id} differs from its source or case text")
        case["source_session"] = (reader.session_id_from_rollout(Path(source)) or
                                  reader.session_id_from_path(Path(source)) or str(Path(source).resolve()))
    discovery_sessions = {case["source_session"] for case in cases if case["split"] == "discovery"}
    if any(case["source_session"] in discovery_sessions for case in cases if case["split"] == "validation"):
        raise CatalogError("Validation evidence must come from sessions separate from discovery")
    return cases


def promote(data_repo: str | Path, candidate_path: str | Path) -> dict[str, Any]:
    root = Path(data_repo)
    current = load_catalog(root)
    candidate = validate_catalog(_read_json(Path(candidate_path)))
    cases = _cases(root)
    if not any(c["split"] == "validation" and c["expected_match"] for c in cases) or not any(
            c["split"] == "validation" and not c["expected_match"] for c in cases):
        raise CatalogError("Promotion requires untouched validation positive and negative cases")
    old_by_id = {item["id"]: item for item in current["detectors"]}
    changed = [item for item in candidate["detectors"] if item != old_by_id.get(item["id"])]
    if not changed:
        raise CatalogError("Candidate contains no changed detectors")
    for detector in changed:
        if not any(c["split"] == "discovery" and c["expected_match"] and
                   c["evidence_id"] in detector["evidence_ids"] and
                   detector["id"] in {m["pattern_id"] for m in match_patterns(
                       c["text"], c["role"], c["phase"], candidate)} for c in cases):
            raise CatalogError(f"{detector['id']} lacks a matching motivating discovery case")
        if not any(c["split"] == "validation" and c["expected_match"] and
                   detector["id"] in {m["pattern_id"] for m in match_patterns(
                       c["text"], c["role"], c["phase"], candidate)} for c in cases):
            raise CatalogError(f"{detector['id']} lacks a matching independent validation case")
        if not any(c["split"] == "validation" and not c["expected_match"] and
                   c["role"] in detector["roles"] and c["phase"] in detector["phases"] for c in cases):
            raise CatalogError(f"{detector['id']} lacks an applicable validation negative case")
    for case in cases:
        before = {m["pattern_id"] for m in match_patterns(case["text"], case["role"], case["phase"], current)}
        after = {m["pattern_id"] for m in match_patterns(case["text"], case["role"], case["phase"], candidate)}
        if case["expected_match"] and (not after or not before <= after):
            raise CatalogError(f"Candidate loses known positive case {case.get('id', case['evidence_id'])}")
        if not case["expected_match"] and after:
            raise CatalogError(f"Candidate matches known false positive {case.get('id', case['evidence_id'])}")
    candidate["version"] = current["version"] + 1
    catalog_dir = root / "catalog"
    _atomic_json(catalog_dir / "versions" / f"version-{current['version']}.json", current)
    _atomic_json(catalog_dir / "active.json", candidate)
    return candidate


def rollback(data_repo: str | Path, target_version: int) -> dict[str, Any]:
    root = Path(data_repo)
    current = load_catalog(root)
    target = validate_catalog(_read_json(root / "catalog" / "versions" / f"version-{target_version}.json"))
    result = {**target, "version": current["version"] + 1, "rollback_of": target_version}
    _atomic_json(root / "catalog" / "versions" / f"version-{current['version']}.json", current)
    _atomic_json(root / "catalog" / "active.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-repo")
    parser.add_argument("--config")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    promotion = commands.add_parser("promote")
    promotion.add_argument("candidate")
    reversal = commands.add_parser("rollback")
    reversal.add_argument("version", type=int)
    args = parser.parse_args(argv)
    try:
        if not args.data_repo:
            from slop_config import load_config
            args.data_repo = load_config(args.config)["data_repo"]
        result = (load_catalog(args.data_repo) if args.command == "validate" else
                  promote(args.data_repo, args.candidate) if args.command == "promote" else
                  rollback(args.data_repo, args.version))
    except (CatalogError, ValueError, OSError) as exc:
        parser.exit(2, f"slop catalog: {exc}\n")
    print(json.dumps({"version": result["version"], "detectors": len(result["detectors"])}))
    return 0


if __name__ == "__main__":
    main()
