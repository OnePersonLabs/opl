#!/usr/bin/env python3
"""Remind agents to refresh local plugins after marketplace Git pushes and pulls."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


def git_operation(command, directory):
    """Recognize a direct Git push/pull and its effective -C directory."""
    try:
        lexer = shlex.shlex(command, posix=os.name != "nt", punctuation_chars=";&|()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens or tokens[0].strip("\"'").lower() not in ("git", "git.exe"):
        return None

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in ("push", "pull"):
            return token, directory
        if token == "--no-pager":
            index += 1
            continue
        if token in ("-C", "-c"):
            if index + 1 >= len(tokens):
                return None
            value = tokens[index + 1].strip("\"'")
            if token == "-C":
                directory = (directory / value).resolve()
            index += 2
            continue
        if token.startswith("-C") and len(token) > 2:
            directory = (directory / token[2:].strip("\"'")).resolve()
            index += 1
            continue
        return None
    return None


def repository_root(directory):
    result = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f"invalid hook input: {error}") from None
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "PostToolUse" or payload.get("tool_name") != "Bash":
        return
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    command = tool_input.get("command", tool_input.get("cmd"))
    if not isinstance(command, str):
        return

    session_directory = payload.get("cwd") or os.environ.get("CODEX_PROJECT_DIR") or os.getcwd()
    workdir = tool_input.get("workdir") or session_directory
    directory = Path(session_directory, workdir).resolve()
    operation = git_operation(command, directory)
    if operation is None:
        return
    verb, target_directory = operation
    root = repository_root(target_directory)
    if root is None or not (root / ".agents" / "plugins" / "marketplace.json").is_file():
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"If the git {verb} succeeded, invoke $opl:refresh-local-plugins "
                "for this local plugin marketplace. Follow the skill's plugin "
                "selection and authorized Codex home requirements."
            ),
        },
    }))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"codex-marketplace-refresh-hook: {error}", file=sys.stderr)
        sys.exit(1)
