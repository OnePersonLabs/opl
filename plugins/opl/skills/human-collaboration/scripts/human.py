#!/usr/bin/env python3
"""Command and hook entry point for OPL's human contribution inbox."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.dont_write_bytecode = True
from inbox import Inbox, InboxError, discover


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--workspace", default=os.getcwd())
    value.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"))
    actions = value.add_subparsers(dest="command", required=True)
    actions.add_parser("init")
    actions.add_parser("hook")
    actions.add_parser("list")
    actions.add_parser("pending")
    actions.add_parser("refresh")
    bind = actions.add_parser("bind")
    bind.add_argument("--reason", required=True)
    contribute = actions.add_parser("contribute", help="submit a human-initiated contribution")
    contribute.add_argument("note", help="JSON with title, body and a stable request_id; file or - for stdin")
    contribute.add_argument("--notify", action="store_true")
    publish = actions.add_parser("publish")
    publish.add_argument("spec", help="JSON spec file, or - for stdin")
    revise = actions.add_parser("revise")
    revise.add_argument("item")
    revise.add_argument("spec")
    revise.add_argument("--reason", required=True)
    show = actions.add_parser("show")
    show.add_argument("item")
    show.add_argument("--revision", type=int)
    submit = actions.add_parser("submit", help="snapshot the Markdown # Reply explicitly")
    submit.add_argument("item")
    submit.add_argument("--revision", type=int)
    submit.add_argument("--kind", choices=("feedback", "question"), default="feedback")
    submit.add_argument("--notify", action="store_true")
    claim = actions.add_parser("claim")
    claim.add_argument("submission")
    outcome = actions.add_parser("outcome")
    outcome.add_argument("submission")
    outcome.add_argument("result", help="JSON outcome file, or - for stdin")
    for name in ("start", "later", "ready", "retire", "rank"):
        action = actions.add_parser(name)
        action.add_argument("item")
        if name != "start":
            action.add_argument("--reason", required=True)
        if name == "rank":
            action.add_argument("--priority", type=int, required=True)
    notification = actions.add_parser("notify")
    notification.add_argument("submission")
    notification.add_argument("--retry", action="store_true")
    serve = actions.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--allow-lan", action="store_true")
    serve.add_argument("--wake-root", action="store_true")
    return value


def read_json(path: str) -> dict:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise InboxError("input must be a JSON object")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "hook":
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise InboxError("hook input must be an object")
            workspace = discover(Path(payload.get("cwd") or args.workspace))
            result = Inbox(workspace).hook(payload) if workspace else {}
        else:
            inbox = Inbox(args.workspace)
            command = args.command
            if command == "init":
                result = inbox.init(args.thread)
            elif command == "bind":
                result = inbox.bind(args.thread, args.reason)
            elif command == "contribute":
                note = read_json(args.note)
                result = inbox.contribute(note.get("title"), note.get("body"), note.get("request_id"))
                if args.notify:
                    from server import notify
                    result["notification"] = notify(inbox, result["id"])
            elif command == "publish":
                result = inbox.publish(read_json(args.spec), args.thread)
            elif command == "revise":
                result = inbox.revise(args.item, read_json(args.spec), args.reason, args.thread)
            elif command == "show":
                result = inbox.get(args.item, args.revision)
            elif command == "refresh":
                inbox.refresh()
                result = {"inbox": str(inbox.root / "INBOX.md"), "decisions": str(inbox.root / "DECISIONS.md")}
            elif command == "list":
                result = inbox.snapshot()
            elif command == "pending":
                # A compact recovery index; fetch only the relevant full item next.
                result = [{key: receipt[key] for key in ("id", "item", "revision", "kind", "state", "claimed_by", "created", "queue")}
                          for receipt in inbox.snapshot()["pending"]]
            elif command == "submit":
                result = inbox.submit_file(args.item, args.revision, args.kind)
                if args.notify:
                    from server import notify
                    result["notification"] = notify(inbox, result["id"])
            elif command == "claim":
                result = inbox.claim(args.submission, args.thread)
            elif command == "outcome":
                result = inbox.outcome(args.submission, read_json(args.result), args.thread)
            elif command in {"start", "later", "ready", "retire", "rank"}:
                result = inbox.move(args.item, command, getattr(args, "reason", ""), getattr(args, "priority", None), args.thread)
            elif command == "notify":
                from server import notify
                result = notify(inbox, args.submission, retry=args.retry)
            elif command == "serve":
                from server import HumanServer
                address = ipaddress.ip_address(args.host)
                if not address.is_loopback and not args.allow_lan:
                    raise InboxError("non-loopback binding requires --allow-lan; use a trusted LAN or VPN, not public HTTP")
                if not 0 <= args.port <= 65535:
                    raise InboxError("port must be between 0 and 65535")
                inbox.refresh()
                server = HumanServer(inbox, args.host, args.port, wake=args.wake_root)
                host = f"[{args.host}]" if address.version == 6 else args.host
                print(json.dumps({"url": f"http://{host}:{server.server_address[1]}/#token={server.token}",
                                  "workspace": str(inbox.workspace), "wake_root": args.wake_root,
                                  "note": "For wildcard binding, replace the wildcard with this device's reachable LAN/VPN IP. HTTP is not encrypted."}), flush=True)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
                finally:
                    server.server_close()
                return 0
            else:
                raise InboxError("unsupported command")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (InboxError, OSError, ValueError, TypeError, sqlite3.Error) as error:
        print(f"human-collaboration: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
