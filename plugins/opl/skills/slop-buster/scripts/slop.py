#!/usr/bin/env python3
"""Single entrypoint for Slop Buster's tools and launcher."""
from __future__ import annotations

import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    config_args = []
    if "--config" in args:
        index = args.index("--config")
        if index + 1 >= len(args):
            print("--config requires a path", file=sys.stderr)
            return 2
        config_args = args[index:index + 2]
        del args[index:index + 2]
    if not args or args[0] in ("-h", "--help"):
        print("Slop Buster: setup | daily | prepare | next | record | capture | incidents | finish | status | show | register-session | feedback | catalog")
        print("Use COMMAND --help. The skill orchestrates run/full/audit/capture modes.")
        return 0
    command = args.pop(0)
    if command == "setup":
        from slop_setup import main as entry
    elif command == "daily":
        from slop_daily import main as entry
    elif command == "catalog":
        from slop_catalog import main as entry
    else:
        from slop_audit import main as entry
        args.insert(0, command)
    return entry(config_args + args)


if __name__ == "__main__":
    raise SystemExit(main())
