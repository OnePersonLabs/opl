#!/usr/bin/env python3
"""Report local OPL instruction updates without injecting stock instructions."""

import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(os.environ.get("PLUGIN_ROOT") or Path(__file__).resolve().parent.parent).resolve()
sys.path.insert(0, str(ROOT / "skills" / "update-instructions" / "scripts"))
from instructions import home_path, snapshot


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid hook input: {error}") from None
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    event = payload.get("hook_event_name", "SessionStart")
    if event != "SessionStart":
        raise ValueError(f"unsupported hook event: {event}")

    state = snapshot(home_path(), ROOT)
    if state["status"] == "current":
        print("{}")
        return
    messages = {
        "setup": "OPL instructions are not set up in your active global instructions.",
        "update": f"OPL instructions version {state['bundled_version']} is available (your baseline: {state['user_version']}).",
        "newer": f"Your OPL instructions baseline ({state['user_version']}) is newer than installed OPL ({state['bundled_version']}). Keep your instructions; update the installed plugin rather than downgrade them.",
        "invalid": "Your OPL instructions version marker is invalid.",
    }
    message = messages[state["status"]] + f" File: {state['target']}"
    if state["status"] in {"setup", "update", "invalid"}:
        guidance = (
            f" Before continuing the user's pending task, ask once whether to replace this file with "
            f"the installed OPL instructions at version {state['bundled_version']}. Explain that "
            "active custom rules will be replaced, the old file will be saved byte for byte in a "
            "dated backup, and the rules will not be merged. Stop and wait for the reply. If the user "
            "agrees, run $opl:update-instructions and treat that yes as approval to apply the "
            "installed instructions; do not ask for a second approval. If the user declines, do not "
            "run the skill. After either branch is complete, resume the user's pending task."
        )
    else:
        guidance = " Briefly notify the user and continue the pending task; do not downgrade or change instructions automatically."
    message += " Do not reply to this reminder itself. If the requested action is already complete, ignore this message."
    print(json.dumps({"systemMessage": message, "hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": message + guidance,
    }}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, ValueError) as error:
        print(f"codex-agents-context-hook: {error}", file=sys.stderr)
        sys.exit(1)
