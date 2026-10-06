#!/usr/bin/env python3
"""Command and hook entry point for OPL's human contribution inbox."""
from __future__ import annotations

import argparse
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
    initialize = actions.add_parser("init")
    initialize.add_argument("--title")
    actions.add_parser("hook")
    actions.add_parser("list")
    actions.add_parser("pending")
    actions.add_parser("refresh")
    bind = actions.add_parser("bind")
    bind.add_argument("--reason", required=True)
    bind.add_argument("--from-thread", help="session to transfer; required when several roots are registered")
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
    assume = actions.add_parser("assume")
    assume.add_argument("item")
    assume.add_argument("--question", action="append", required=True)
    assume.add_argument("--reason", required=True)
    assume.add_argument("--revision", type=int)
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
    for name in ("serve", "connect"):
        serve = actions.add_parser(name)
        serve.add_argument("--host", default="127.0.0.1", help="literal bind IP, or lan to detect a private LAN IPv4 address")
        serve.add_argument("--port", type=int, default=8766)
        serve.add_argument("--allow-lan", action="store_true")
        serve.add_argument("--wake-root", action="store_true")
        serve.add_argument("--register-workspace", action="append", default=[], help="additional initialized workspace to register locally")
        serve.add_argument("--catalog", help=argparse.SUPPRESS)
        if name == "serve":
            serve.add_argument("--console", action="store_true", help=argparse.SUPPRESS)
            serve.add_argument("--managed", action="store_true", help=argparse.SUPPRESS)
    for name, description in (("pause-for-refresh", "record whether the service is running and stop it if so"),
                             ("resume-after-refresh", "restart the service only if it ran before refresh")):
        lifecycle = actions.add_parser(name, help=description)
        lifecycle.add_argument("--catalog", help=argparse.SUPPRESS)
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
        if args.command == "serve" and args.console:
            from service import open_console
            open_console()
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
                result = inbox.init(args.thread, args.title)
                from catalog import Catalog
                Catalog().register(inbox)
            elif command == "bind":
                result = inbox.bind(args.thread, args.reason, args.from_thread)
            elif command == "contribute":
                note = read_json(args.note)
                result = inbox.contribute(note.get("title"), note.get("body"), note.get("request_id"), args.thread)
                if args.notify:
                    from server import notify
                    result["notification"] = notify(inbox, result["id"], thread=args.thread)
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
                result = inbox.snapshot(args.thread)
            elif command == "pending":
                # A compact recovery index; fetch only the relevant full item next.
                result = [{key: receipt[key] for key in ("id", "item", "revision", "kind", "state", "claimed_by", "created", "queue")}
                          for receipt in inbox.snapshot(args.thread)["pending"]]
            elif command == "submit":
                result = inbox.submit_file(args.item, args.revision, args.kind)
                if args.notify:
                    from server import notify
                    result["notification"] = notify(inbox, result["id"], thread=args.thread)
            elif command == "claim":
                result = inbox.claim(args.submission, args.thread)
            elif command == "outcome":
                result = inbox.outcome(args.submission, read_json(args.result), args.thread)
            elif command == "assume":
                result = inbox.assume(args.item, args.question, args.reason, args.thread, args.revision)
            elif command in {"start", "later", "ready", "retire", "rank"}:
                result = inbox.move(args.item, command, getattr(args, "reason", ""), getattr(args, "priority", None), args.thread)
            elif command == "notify":
                from server import notify
                result = notify(inbox, args.submission, retry=args.retry, thread=args.thread)
            elif command in {"pause-for-refresh", "resume-after-refresh"}:
                from catalog import Catalog
                from service import pause_for_refresh, resume_after_refresh
                catalog = Catalog(Path(args.catalog)) if args.catalog else Catalog()
                if command == "pause-for-refresh":
                    result = pause_for_refresh(catalog, inbox.workspace)
                else:
                    result = resume_after_refresh(inbox, catalog)
            elif command in {"serve", "connect"}:
                from server import HumanServer
                from catalog import Catalog
                from service import configure_activity, connect, receipt, save_receipt, validate_address
                if args.host == "lan":
                    if not args.allow_lan:
                        raise InboxError("LAN startup requires --allow-lan")
                    from network import lan_address
                    args.host = lan_address()
                validate_address(args.host, args.port, args.allow_lan)
                catalog = (Catalog(Path(args.catalog)) if args.catalog else
                           (Catalog() if command == "connect" else Catalog(inboxes=[inbox])))
                catalog.register(inbox)
                for workspace in args.register_workspace:
                    catalog.register(Inbox(workspace))
                inbox.refresh()
                if command == "connect":
                    result = connect(inbox, args.host, args.port, allow_lan=args.allow_lan, wake=args.wake_root, catalog=catalog)
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                    return 0
                # Managed POSIX startup already redirects stderr to service.log.
                activity = configure_activity(catalog, file_log=not args.managed)
                activity.info("starting listener host=%s port=%s", args.host, args.port)
                server = HumanServer(inbox, args.host, args.port, wake=args.wake_root, catalog=catalog)
                value = receipt(server, args.host, catalog)
                if catalog.directory is not None:
                    save_receipt(catalog, value)
                if not (args.console or args.managed):
                    print(json.dumps(value), flush=True)
                elif args.console:
                    # The user needs a usable link in the visible window. Keep
                    # it out of the activity logger and its persistent log file.
                    print("Pairing URL: " + value["url"], flush=True)
                activity.info("listener ready host=%s port=%s pid=%s; Ctrl+C stops the server%s",
                              args.host, server.server_port, os.getpid(), "; closing this window also stops it" if args.console else "")
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
                finally:
                    activity.info("stopping listener")
                    server.server_close()
                    activity.info("listener stopped")
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
