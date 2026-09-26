#!/usr/bin/env python3
"""Durable, bounded bookkeeping for reviewed Codex harness curation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
SCHEMA = 1
MODELS = {"executor": "gpt-6-luna", "evaluator": "gpt-6-sol"}
PHASES = {"capability", "selection", "recovery"}


def read(path):
    if Path(path).is_symlink():
        raise ValueError("refusing to read a symlinked state or input file")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("refusing to replace a symlinked artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = Path(stream.name)
            stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def state_root(home):
    home = Path(home).expanduser().resolve()
    root = home / "opl" / "harness"
    if not root.resolve().is_relative_to(home):
        raise ValueError("harness state must remain inside the selected Codex home")
    return root


@contextmanager
def lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".write-lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(f"another writer or interrupted operation owns {path}; inspect before removing the lock") from None
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink()


def init(home):
    root = state_root(home)
    with lock(root):
        path = root / "decisions.json"
        if not path.exists():
            write(path, {"schemaVersion": SCHEMA, "categories": {}})
    return {"root": str(root), "decisions": str(path)}


def cards(home, kind=None, source=None, query=None, offset=0, limit=6):
    positive(offset, "offset", zero=True)
    positive(limit, "limit")
    if limit > 25:
        raise ValueError("card pages are limited to 25 items")
    inventory = read(state_root(home) / "inventory.json")
    items = [item for item in inventory["items"] if (not kind or item["kind"] == kind)
             and (not source or item["source"] == source)
             and (not query or query.casefold() in (item.get("name", "") + " " + item.get("description", "")).casefold())]
    fields = ("id", "kind", "name", "source", "plugin", "path", "enabled", "available", "summary", "estimatedTokens", "tokenEstimateBasis", "implicitInvocation")
    return {"total": len(items), "offset": offset, "nextOffset": offset + limit if offset + limit < len(items) else None,
            "items": [{key: item[key] for key in fields if key in item} for item in items[offset:offset + limit]]}


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise ValueError(f"{label} must be a short identifier without path separators")
    return value


def positive(value, label, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f"{label} must be {'nonnegative' if zero else 'positive'} integer")
    return value


def validate_cases(cases, candidates):
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    seen = set()
    for case in cases:
        key = identifier(case.get("id"), "case id")
        if key in seen:
            raise ValueError("case IDs must be unique")
        seen.add(key)
        if case.get("candidateId") not in candidates:
            raise ValueError("each case must name a selected candidate")
        if case.get("phase") not in PHASES:
            raise ValueError("case phase must be capability, selection, or recovery")
        if case["phase"] != "capability" and (not isinstance(case.get("executionModel"), str) or not case["executionModel"].strip()):
            raise ValueError("selection and recovery cases require the intended executionModel")
        for key in ("scenario", "rubric"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"case {key} is required")
        if not isinstance(case.get("allowedEffects"), list):
            raise ValueError("case allowedEffects must be an explicit list (empty is allowed)")


def plan(home, spec):
    candidates = spec.get("candidates")
    if not isinstance(candidates, dict) or not candidates or any(not isinstance(v, str) or not v for v in candidates.values()):
        raise ValueError("candidates must map selected IDs to exact version or content-hash strings")
    if spec.get("models") != MODELS:
        raise ValueError("models must explicitly select executor gpt-6-luna and evaluator gpt-6-sol")
    budget = spec.get("budget", {})
    positive(budget.get("maxCases"), "maxCases")
    positive(budget.get("maxToolCalls"), "maxToolCalls")
    positive(budget.get("maxFollowupCases", 0), "maxFollowupCases", zero=True)
    if budget.get("maxFollowupCases", 0) > budget["maxCases"]:
        raise ValueError("follow-up ceiling cannot exceed total case ceiling")
    cases = spec.get("cases")
    validate_cases(cases, candidates)
    if len(cases) > budget["maxCases"]:
        raise ValueError("initial cases exceed maxCases")
    root = state_root(home)
    with lock(root):
        run = uuid.uuid4().hex
        folder = root / "runs" / run
        if not folder.resolve().is_relative_to(root.resolve()):
            raise ValueError("run directory escapes harness state")
        manifest = {"schemaVersion": SCHEMA, "id": run, "candidates": candidates, "models": MODELS,
                    "budget": {**budget, "maxFollowupCases": budget.get("maxFollowupCases", 0)},
                    "cases": cases, "followupUsed": False}
        write(folder / "manifest.json", manifest)
    return {"run": run, "manifest": str(folder / "manifest.json"), "evidence": str(folder / "evidence.jsonl")}


def run_folder(home, run):
    root = state_root(home)
    path = root / "runs" / identifier(run, "run")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("run directory escapes harness state")
    if not (path / "manifest.json").is_file():
        raise ValueError("unknown run")
    return path


def evidence(folder):
    path = folder / "evidence.jsonl"
    if path.is_symlink():
        raise ValueError("refusing symlinked evidence log")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def followup(home, run, spec):
    folder = run_folder(home, run)
    with lock(folder):
        manifest = read(folder / "manifest.json")
        records = evidence(folder)
        if manifest["followupUsed"]:
            raise ValueError("the one follow-up batch is already allocated")
        if sum(row["toolCalls"] for row in records) >= manifest["budget"]["maxToolCalls"]:
            raise ValueError("tool-call budget exhausted")
        if not isinstance(spec.get("reason"), str) or not spec["reason"].strip():
            raise ValueError("follow-up must identify the decision-changing uncertainty")
        cases = spec.get("cases")
        validate_cases(cases, manifest["candidates"])
        if len(cases) > manifest["budget"]["maxFollowupCases"]:
            raise ValueError("follow-up exceeds its approved case ceiling")
        if len(manifest["cases"]) + len(cases) > manifest["budget"]["maxCases"]:
            raise ValueError("follow-up exceeds the total approved case ceiling")
        if {case["id"] for case in cases} & {case["id"] for case in manifest["cases"]}:
            raise ValueError("follow-up case IDs must be new")
        manifest["cases"].extend(cases)
        manifest["followupUsed"] = True
        manifest["followupReason"] = spec["reason"]
        write(folder / "manifest.json", manifest)
    return {"run": run, "casesAdded": len(cases)}


def record(home, run, entry):
    folder = run_folder(home, run)
    with lock(folder):
        manifest = read(folder / "manifest.json")
        cases = {case["id"]: case for case in manifest["cases"]}
        key = entry.get("caseId")
        if key not in cases:
            raise ValueError("record must refer to a planned case")
        if entry.get("status") not in {"success", "failed", "blocked", "skipped"}:
            raise ValueError("record status must be success, failed, blocked, or skipped")
        positive(entry.get("toolCalls"), "toolCalls", zero=True)
        no_executor = entry.get("model") is None and entry["status"] in {"blocked", "skipped"} and entry["toolCalls"] == 0
        expected_model = MODELS["executor"] if cases[key]["phase"] == "capability" else cases[key]["executionModel"]
        if not no_executor and entry.get("model") != expected_model:
            raise ValueError("record the planned executing model; report unavailable rather than substitute")
        if not isinstance(entry.get("observation"), str) or not entry["observation"].strip():
            raise ValueError("record an observation, including why blocked or skipped")
        usage = entry.get("usage")
        if usage is not None:
            if not isinstance(usage, dict) or set(usage) - {"inputTokens", "cachedInputTokens", "outputTokens"}:
                raise ValueError("usage must contain observed token counters only, or null when unavailable")
            for counter, value in usage.items():
                positive(value, counter, zero=True)
        artifacts = entry.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise ValueError("artifacts must be relative paths inside this run")
        hashes = {}
        for name in artifacts:
            path = (folder / name).resolve()
            if Path(name).is_absolute() or not path.is_relative_to(folder.resolve()) or not path.is_file():
                raise ValueError("evidence artifacts must be existing files inside the run")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = evidence(folder)
        if any(row["caseId"] == key for row in rows):
            raise ValueError("case already recorded; plan a distinct follow-up rather than overwrite evidence")
        exceeded = sum(row["toolCalls"] for row in rows) + entry["toolCalls"] > manifest["budget"]["maxToolCalls"]
        row = {"caseId": key, "candidateId": cases[key]["candidateId"], "phase": cases[key]["phase"],
               "model": entry.get("model"), "status": entry["status"], "toolCalls": entry["toolCalls"], "usage": usage,
               "observation": entry["observation"], "artifacts": artifacts, "artifactSha256": hashes, "budgetExceeded": exceeded}
        # Preserve actual evidence even if an executor exceeded its allocation.
        with (folder / "evidence.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return {"run": run, "caseId": key, "budgetExceeded": exceeded, "stopExecution": exceeded}


def report(home, run, assessment):
    folder = run_folder(home, run)
    with lock(folder):
        manifest = read(folder / "manifest.json")
        rows = {row["caseId"]: row for row in evidence(folder)}
        for row in rows.values():
            for name, digest in row.get("artifactSha256", {}).items():
                artifact = (folder / name).resolve()
                if not artifact.is_relative_to(folder.resolve()) or not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
                    raise ValueError("recorded evidence artifact changed or is missing; preserve original evidence and rerun the affected case")
        if assessment.get("model") != MODELS["evaluator"]:
            raise ValueError("report requires the selected Sol evaluator")
        recommendations = assessment.get("recommendations")
        if not isinstance(recommendations, list) or not recommendations:
            raise ValueError("report requires recommendations")
        for item in recommendations:
            if item.get("candidateId") not in manifest["candidates"]:
                raise ValueError("recommendation references an unselected candidate")
            if item.get("verdict") not in {"supported", "conditional", "inconclusive", "rejected"}:
                raise ValueError("invalid recommendation verdict")
            refs = item.get("caseIds")
            if not isinstance(refs, list) or any(ref not in rows or rows[ref]["candidateId"] != item["candidateId"] for ref in refs):
                raise ValueError("recommendations must reference recorded case IDs")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise ValueError("recommendation needs a reason")
            if item["verdict"] != "inconclusive" and (not refs or all(rows[ref]["status"] in {"blocked", "skipped"} for ref in refs)):
                raise ValueError("blocked or absent experiments cannot support a conclusive verdict")
            if item["verdict"] in {"supported", "conditional"} and not any(rows[ref]["status"] == "success" for ref in refs):
                raise ValueError("a positive capability verdict requires a successful observation")
        result = {"schemaVersion": SCHEMA, "model": MODELS["evaluator"], "recommendations": recommendations,
                  "missingCases": sorted({c["id"] for c in manifest["cases"]} - rows.keys()),
                  "budgetExceeded": any(row["budgetExceeded"] for row in rows.values()),
                  "evidenceSha256": hashlib.sha256((folder / "evidence.jsonl").read_bytes()).hexdigest() if rows else None}
        write(folder / "report.json", result)
    return {"report": str(folder / "report.json"), "missingCases": result["missingCases"]}


def decide(home, decision):
    key = identifier(decision.get("category"), "category")
    if decision.get("status") not in {"selected", "excluded", "deferred", "reviewed", "applied"}:
        raise ValueError("invalid category status")
    if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
        raise ValueError("decision reason is required")
    root = state_root(home)
    with lock(root):
        path = root / "decisions.json"
        state = read(path) if path.exists() else {"schemaVersion": SCHEMA, "categories": {}}
        state["categories"][key] = decision
        write(path, state)
    return {"category": key, "status": decision["status"], "decisions": str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "discover", "cards", "plan", "followup", "record", "report", "decide", "prepare", "apply", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--home", type=Path, required=True)
        if name == "cards":
            command.add_argument("--kind", choices=["plugin", "skill", "mcp", "cli"])
            command.add_argument("--source")
            command.add_argument("--query")
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=6)
        if name == "discover":
            command.add_argument("--cwd", type=Path, required=True)
            command.add_argument("--marketplace", type=Path, action="append", default=[])
            command.add_argument("--cli", action="append", default=[])
        if name in {"followup", "record", "report"}:
            command.add_argument("--run", required=True)
        option = {"plan": "spec", "followup": "spec", "record": "record", "report": "report", "decide": "decision", "prepare": "files", "apply": "plan", "rollback": "receipt"}.get(name)
        if option:
            command.add_argument("--" + option, type=Path, required=True)
        if name == "prepare":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        result = init(args.home)
    elif args.command == "cards":
        result = cards(args.home, args.kind, args.source, args.query, args.offset, args.limit)
    elif args.command == "discover":
        from discovery import discover
        result = discover(args.cwd, args.home, args.marketplace, args.cli)
        root = state_root(args.home)
        with lock(root):
            write(root / "inventory.json", result)
        result = {"inventory": str(root / "inventory.json"), "items": len(result["items"]), "complete": result["complete"], "diagnostics": result["diagnostics"]}
    elif args.command in {"plan", "decide"}:
        result = globals()[args.command](args.home, read(getattr(args, "spec" if args.command == "plan" else "decision")))
    elif args.command in {"followup", "record", "report"}:
        result = globals()[args.command](args.home, args.run, read(getattr(args, "spec" if args.command == "followup" else args.command)))
    else:
        from application import prepare, apply, rollback
        if args.command == "prepare":
            result = prepare(args.home, read(args.files))
            if args.output.exists():
                raise ValueError("prepared plan output must not already exist")
            write(args.output, result)
            result = {"plan": str(args.output.resolve())}
        else:
            result = apply(args.home, read(args.plan)) if args.command == "apply" else rollback(args.home, read(args.receipt))
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
