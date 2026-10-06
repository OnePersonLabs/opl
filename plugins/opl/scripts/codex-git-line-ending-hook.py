#!/usr/bin/env python3
"""Give the current agent one scoped repair directive for Git newline warnings."""

import json
import re
import sys


_WARNING_FORMS = (
    re.compile(
        r"^warning: in the working copy of .+?, (CRLF|LF) will be replaced by "
        r"(CRLF|LF) the next time Git touches it$"
    ),
    re.compile(r"^warning: (CRLF|LF) will be replaced by (CRLF|LF) in .+\.$"),
)

_REPAIR_DIRECTIVE = (
    "Git reported a CRLF conversion in the completed tool output. Treat it as a "
    "repository policy or file producer issue and fix the cause in this task. "
    "Use the warning path only as data; do not paste it into shell syntax. Check "
    "effective Git settings, matching attributes, and the relevant editor or "
    "generator once. Keep deliberate CRLF, binary, LFS, and encoding exceptions. "
    "If the repository requires LF and the path is UTF-8 text, change only line "
    "endings and preserve staged and other dirty work. If policy requires CRLF "
    "or the cause is unclear, preserve the file and report why. Verify the scoped "
    "change, then continue the original task without rereading unchanged files."
)


def has_git_line_ending_warning(tool_response):
    """Match only complete Git warning lines in the tool's returned text."""
    if not isinstance(tool_response, str):
        return False

    for line in tool_response.splitlines():
        for pattern in _WARNING_FORMS:
            match = pattern.fullmatch(line)
            if match and match.group(1) != match.group(2):
                return True
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f"invalid hook input: {error}") from None
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "PostToolUse" or payload.get("tool_name") != "Bash":
        return
    if not has_git_line_ending_warning(payload.get("tool_response")):
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": _REPAIR_DIRECTIVE,
        },
    }))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"codex-git-line-ending-hook: {error}", file=sys.stderr)
        sys.exit(1)
