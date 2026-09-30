"""Pack routed conversation records into replay chunks at user-turn boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=80000)
    parser.add_argument("--dedupe-exact", action="store_true", help="Replace repeated exact message bodies with first occurrence pointers in replay only")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.max_bytes < 1:
        raise ValueError("--max-bytes must be positive")
    if any(args.output.iterdir()):
        raise ValueError(f"packet output must be empty: {args.output}")
    rows = (json.loads(line) for line in args.conversation.read_text(encoding="utf-8").splitlines())
    number = 0
    chunk: list[str] = []
    bounds: list[dict[str, object]] = []
    byte_count = 0
    turns: list[tuple[str, int, list[str], list[list[object]]]] = []
    sid = ""
    turn_no = 0
    seen: dict[str, tuple[str, int]] = {}
    for row in rows:
        if row["type"] == "session_start":
            sid = row["session_id"]
            turn_no = 0
            continue
        if row["type"] != "message":
            continue
        if row["role"] == "user" or not turns or turns[-1][0] != sid:
            turn_no += 1
            turns.append((sid, turn_no, [], []))
        body = row["text"]
        if args.dedupe_exact and body in seen and len(body) > 1000:
            first_sid, first_no = seen[body]
            body = f"[Exact repeated message body; see {first_sid} M{first_no}; SHA-256 {row['text_sha256']}]"
        else:
            seen[body] = (sid, row["message_no"])
        turns[-1][2].append(
            f"\n[{sid} M{row['message_no']} {row['timestamp']} {row['role']}/{row['phase']} span={row['source_span']}]\n{body}\n"
        )
        turns[-1][3].append([sid, row["message_no"]])

    def flush() -> None:
        nonlocal number, chunk, bounds, byte_count, refs
        if not chunk:
            return
        number += 1
        path = args.output / f"{number:04d}.txt"
        content = "".join(chunk).encode("utf-8")
        path.write_bytes(content)
        manifest.append({"chunk": path.name, "bytes": len(content),
                         "sha256": hashlib.sha256(content).hexdigest(), "bounds": bounds,
                         "message_refs": refs})
        chunk, bounds, byte_count, refs = [], [], 0, []

    manifest: list[dict[str, object]] = []
    refs: list[list[object]] = []
    for turn_sid, turn_number, parts, turn_refs in turns:
        content = "".join(parts)
        size = len(content.encode("utf-8"))
        if chunk and byte_count + size > args.max_bytes:
            flush()
        chunk.append(content)
        refs.extend(turn_refs)
        byte_count += size
        if bounds and bounds[-1]["session_id"] == turn_sid:
            bounds[-1]["turns"][1] = turn_number
        else:
            bounds.append({"session_id": turn_sid, "turns": [turn_number, turn_number]})
    flush()
    (args.output / "manifest.jsonl").write_bytes(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in manifest).encode("utf-8")
    )
    print(json.dumps({"chunks": len(manifest), "oversized": sum(item["bytes"] > args.max_bytes for item in manifest)}))


if __name__ == "__main__":
    main()
