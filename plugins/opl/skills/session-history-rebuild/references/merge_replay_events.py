"""Validate and merge per-chunk event extracts in replay order."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


KINDS = {"user_decision", "user_request", "assistant_proposal", "implementation_report", "review_finding", "unknown"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conversation", type=Path, help="Verify replay headers cover the routed message sequence")
    parser.add_argument("--through", type=int, help="Validate only the first N chunks while replay is in progress")
    args = parser.parse_args()
    manifest = [json.loads(line) for line in (args.chunks / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    if args.through is not None:
        manifest = manifest[: args.through]
    merged: list[dict[str, object]] = []
    observed_headers: list[tuple[str, int]] = []
    for item in manifest:
        stem = Path(item["chunk"]).stem
        chunk_path = args.chunks / item["chunk"]
        event_path = args.events / f"{stem}.jsonl"
        if not event_path.is_file():
            raise ValueError(f"missing event extract for {chunk_path.name}")
        raw = chunk_path.read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"packet integrity mismatch: {chunk_path.name}")
        headers = [(sid, number) for sid, number in item["message_refs"]]
        if any(not isinstance(sid, str) or type(number) is not int or number < 1 for sid, number in headers):
            raise ValueError(f"invalid packet message references: {chunk_path.name}")
        observed_headers.extend(headers)
        allowed = set(headers)
        if not allowed:
            raise ValueError(f"chunk contains no canonical message headers: {chunk_path}")
        for line_no, line in enumerate(event_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            event = json.loads(line)
            for key in ("timestamp", "session_id", "message_numbers", "kind", "statement", "why", "evidence_limit"):
                if key not in event:
                    raise ValueError(f"{event_path.name}:{line_no} missing {key}")
            if event["kind"] not in KINDS:
                raise ValueError(f"{event_path.name}:{line_no} invalid event kind")
            if not isinstance(event["message_numbers"], list) or not event["message_numbers"]:
                raise ValueError(f"{event_path.name}:{line_no} needs message numbers")
            if any(type(number) is not int or (event["session_id"], number) not in allowed
                   for number in event["message_numbers"]):
                raise ValueError(f"{event_path.name}:{line_no} cites a message outside its chunk")
            event["replay_chunk"] = item["chunk"]
            merged.append(event)
    if args.conversation is not None and args.through is None:
        expected_headers = [
            (row["session_id"], row["message_no"])
            for row in (json.loads(line) for line in args.conversation.read_text(encoding="utf-8").splitlines())
            if row["type"] == "message"
        ]
        if observed_headers != expected_headers:
            raise ValueError("replay packet headers do not cover the routed conversation in order")
    args.output.write_bytes("".join(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in merged
    ).encode("utf-8"))
    print(json.dumps({"chunks": len(manifest), "events": len(merged)}))


if __name__ == "__main__":
    main()
