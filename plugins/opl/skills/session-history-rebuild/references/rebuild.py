#!/usr/bin/env python3
"""Export and verify routed histories from a frozen session-reader SQLite index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def encoded(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")


def normalized(path: str) -> str:
    value = path.replace("\\", "/")
    if value != "/" and not re.fullmatch(r"[a-zA-Z]:/+", value):
        value = value.rstrip("/")
    elif re.fullmatch(r"[a-zA-Z]:/+", value):
        value = value[:2] + "/"
    return value.casefold() if re.match(r"^(?:[a-zA-Z]:/|//)", value) else value


def under(path: str, root: str) -> bool:
    value, base = normalized(path), normalized(root)
    return value == base or value.startswith(base if base.endswith("/") else base + "/")


def candidates(db: sqlite3.Connection, roots: list[str], terms: list[str], cutoff: str) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM sessions WHERE created_at<=? ORDER BY created_at,session_id", (cutoff,)).fetchall()
    selected = []
    for row in rows:
        root_hits = [root for root in roots if under(row["cwd"], root)]
        term_hits = [term for term in terms if term.casefold() in row["cwd"].casefold()]
        message_roots = []
        if not root_hits:
            for root in roots:
                variants = {root, root.replace("\\", "/"), root.replace("/", "\\")}
                if any(db.execute(
                    "SELECT 1 FROM messages WHERE session_id=? AND instr(text,?)>0 LIMIT 1",
                    (row["session_id"], variant),
                ).fetchone() for variant in variants):
                    message_roots.append(root)
        if not root_hits and terms:
            term_hits.extend(term for term in terms if db.execute(
                "SELECT 1 FROM messages WHERE session_id=? AND instr(lower(text),lower(?))>0 LIMIT 1",
                (row["session_id"], term),
            ).fetchone())
        selected.append({
            "session_id": row["session_id"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "cwd": row["cwd"], "source_path": row["path"],
            "cwd_sha256": sha(row["cwd"]),
            "candidate_reason": "root" if root_hits else "message-root-reference" if message_roots else "related-term" if term_hits else "unclassified",
            "matched_roots": root_hits + message_roots, "matched_terms": sorted(set(term_hits)),
            "archived": bool(row["archived"]), "indexed_messages": row["message_count"],
            "schema_kind": row["schema_kind"], "malformed_lines": row["malformed_count"],
            "unknown_lines": row["unknown_count"],
        })
    return selected


def numbers(selection: Any, maximum: int) -> set[int]:
    if selection == "all":
        return set(range(1, maximum + 1))
    if selection is None:
        return set()
    if not isinstance(selection, list):
        raise ValueError("selection must be 'all', null, or inclusive ranges")
    chosen: set[int] = set()
    for pair in selection:
        if not isinstance(pair, list) or len(pair) != 2 or any(type(n) is not int for n in pair):
            raise ValueError(f"invalid message range: {pair}")
        first, last = pair
        if first < 1 or last > maximum or first > last:
            raise ValueError(f"out-of-range message range: {pair}")
        chosen.update(range(first, last + 1))
    return chosen


def render(rows: list[dict[str, Any]]) -> bytes:
    parts = []
    for row in rows:
        if row["type"] == "session_start":
            parts.append(f"\n=== Session {row['session_id']} | {row['created_at']} | {row['lineage']} ===\n")
        elif row["type"] == "message":
            parts.append(f"\n[{row['session_id']} M{row['message_no']} {row['timestamp']} {row['role']}/{row['phase']} span={row['source_span']}]\n")
            parts.append(row["text"])
            parts.append("\n")
        else:
            parts.append(f"=== End session {row['session_id']} ===\n")
    return "".join(parts).encode("utf-8")


def build(db: sqlite3.Connection, inventory: list[dict[str, Any]], routes: dict[str, dict[str, Any]], lineage: str, cutoff: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conversation: list[dict[str, Any]] = []
    manifest = []
    for candidate in inventory:
        sid = candidate["session_id"]
        route = routes[sid]
        messages = db.execute("SELECT message_no,raw_line,byte_offset,timestamp,role,phase,source,text FROM messages WHERE session_id=? ORDER BY message_no", (sid,)).fetchall()
        if len(messages) != candidate["indexed_messages"]:
            raise ValueError(f"index message count mismatch: {sid}")
        chosen = numbers(route["lineages"][lineage], len(messages))
        span_map = route.get("spans", {}).get(lineage, {})
        if not isinstance(span_map, dict) or any(not isinstance(key, str) or not re.fullmatch(r"[1-9][0-9]*", key)
                                                 or int(key) not in chosen for key in span_map):
            raise ValueError(f"invalid span message: {sid}")
        selected = [row for row in messages if row["message_no"] in chosen and row["timestamp"] <= cutoff]
        manifest.append({**candidate, "lineage": lineage, "route_reason": route["reason"],
                         "route_status": "included" if selected else "excluded", "selected_messages": len(selected),
                         "after_cutoff_messages": len(chosen) - len(selected)})
        if not selected:
            continue
        conversation.append({"type": "session_start", "session_id": sid, "created_at": candidate["created_at"],
                             "lineage": lineage, "selected_messages": len(selected)})
        for row in selected:
            original = row["text"]
            spans = span_map.get(str(row["message_no"]), [[0, len(original)]])
            if not isinstance(spans, list) or not spans:
                raise ValueError(f"empty spans: {sid} M{row['message_no']}")
            end = 0
            for span in spans:
                if not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span):
                    raise ValueError(f"invalid span: {sid} M{row['message_no']}")
                first, last = span
                if first < end or first < 0 or last > len(original) or first >= last:
                    raise ValueError(f"overlapping or out-of-range span: {sid} M{row['message_no']}")
                end = last
                body = original[first:last]
                conversation.append({"type": "message", "session_id": sid, "message_no": row["message_no"],
                                     "timestamp": row["timestamp"], "role": row["role"], "phase": row["phase"],
                                     "source": row["source"], "raw_line": row["raw_line"],
                                     "byte_offset": row["byte_offset"], "source_span": span,
                                     "source_text_sha256": sha(original),
                                     "text": body, "text_sha256": sha(body)})
        conversation.append({"type": "session_end", "session_id": sid})
    return conversation, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--related-term", action="append", default=[])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory").add_argument("--output", type=Path, required=True)
    for name in ("export", "verify"):
        action = sub.add_parser(name)
        action.add_argument("--routes", type=Path, required=True)
        action.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = args.root or [os.getcwd()]
    db = sqlite3.connect(args.index.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        inventory = candidates(db, roots, args.related_term, args.cutoff)
        if args.command == "inventory":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(encoded(inventory))
            print(json.dumps({"candidates": len(inventory), "output": str(args.output)}))
            return
        items = jsonl(args.routes)
        routes = {item["session_id"]: item for item in items}
        expected = {item["session_id"] for item in inventory}
        if len(routes) != len(items) or set(routes) != expected:
            raise ValueError(f"route coverage mismatch: missing={sorted(expected - set(routes))}, extra={sorted(set(routes) - expected)}")
        lineages = set(items[0]["lineages"]) if items else set()
        if not lineages or any(not isinstance(item.get("reason"), str) or not item["reason"].strip()
                               or not isinstance(item.get("lineages"), dict) or set(item["lineages"]) != lineages
                               or not isinstance(item.get("spans", {}), dict)
                               or set(item.get("spans", {})) - lineages
                               for item in items):
            raise ValueError("each route needs a reason, the same nonempty lineage set, and known span lineages")
        lock = {"index_sha256": file_sha(args.index), "routes_sha256": file_sha(args.routes),
                "cutoff": args.cutoff, "roots": roots, "related_terms": args.related_term,
                "candidate_count": len(inventory)}
        lock_content = (json.dumps(lock, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if args.command == "verify" and (args.output / "source-lock.json").read_bytes() != lock_content:
            raise ValueError("source lock mismatch: index, routes, cutoff, or scope changed")
        result = {}
        products: dict[str, dict[str, bytes]] = {}
        for lineage in sorted(lineages):
            if not lineage or lineage in (".", "..") or Path(lineage).name != lineage or "/" in lineage or "\\" in lineage:
                raise ValueError(f"invalid lineage directory: {lineage}")
            conversation, manifest = build(db, inventory, routes, lineage, args.cutoff)
            files = {"conversation.jsonl": encoded(conversation), "manifest.jsonl": encoded(manifest),
                     "conversation.txt": render(conversation)}
            products[lineage] = files
            if args.command == "verify":
                for filename, content in files.items():
                    dest = args.output / lineage
                    if (dest / filename).read_bytes() != content:
                        raise ValueError(f"frozen index/routes mismatch: {dest / filename}")
            result[lineage] = {"candidates": len(manifest), "sessions": sum(row["type"] == "session_start" for row in conversation),
                               "messages": sum(row["type"] == "message" for row in conversation)}
        if args.command == "export":
            if args.output.exists():
                raise ValueError(f"export output must not already exist: {args.output}")
            parent = args.output.resolve().parent
            parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".session-history-", dir=parent))
            try:
                (staging / "source-lock.json").write_bytes(lock_content)
                for lineage, files in products.items():
                    dest = staging / lineage
                    dest.mkdir()
                    for filename, content in files.items():
                        (dest / filename).write_bytes(content)
                staging.rename(args.output)
            finally:
                if staging.exists():
                    if staging.resolve().parent != parent.resolve() or not staging.name.startswith(".session-history-"):
                        raise ValueError(f"unsafe staging cleanup target: {staging}")
                    shutil.rmtree(staging)
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == "__main__":
    main()
