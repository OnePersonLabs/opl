#!/usr/bin/env python3
"""
Forge a truncated session file for unslop rule development replay.

Takes a Claude Code or Codex session JSONL, truncates it at a specified point,
and writes the result as a new session with a fresh UUID. The forged session
can be resumed with the matching agent's resume command.

Usage:
    python forge-session.py <session-file> <cutpoint> <output-dir> [--agent auto|claude|codex] [--project-dir <dir>]

    cutpoint: line number (1-indexed), UUID prefix, or Codex rollout/session id prefix to cut AFTER
    output-dir: directory to write the forged session into
    --project-dir: agent session dir. For Claude this is usually ~/.claude/projects/<project>.
                   For Codex this is usually ~/.codex/sessions/YYYY/MM/DD.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Literal

AgentKind = Literal["auto", "claude", "codex"]


def detect_agent(lines: list[str], requested: AgentKind) -> Literal["claude", "codex"]:
    if requested != "auto":
        return requested

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") in ("response_item", "event_msg", "session_meta", "turn_context"):
            return "codex"
        if obj.get("type") in ("user", "assistant", "summary") or "sessionId" in obj or "uuid" in obj:
            return "claude"

    return "claude"


def record_id(obj: dict, agent: str) -> str:
    if agent == "codex":
        payload = obj.get("payload")
        if isinstance(payload, dict):
            return str(payload.get("id") or payload.get("turn_id") or payload.get("call_id") or "")
        return ""
    return str(obj.get("uuid", ""))


def find_cutpoint(lines: list[str], cutpoint: str, agent: str) -> int:
    """Return the line index to cut after (exclusive upper bound)."""
    try:
        n = int(cutpoint)
        if 1 <= n <= len(lines):
            return n
        print(f"Line number {n} out of range (1-{len(lines)})", file=sys.stderr)
        sys.exit(1)
    except ValueError:
        pass

    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            uid = record_id(obj, agent)
            if uid.startswith(cutpoint):
                return i + 1  # cut after this line
        except json.JSONDecodeError:
            continue

    print(f"Record/session id prefix '{cutpoint}' not found in session", file=sys.stderr)
    sys.exit(1)


def preview_claude(obj: dict) -> tuple[str, str]:
    t = obj.get("type", "?")
    uid = obj.get("uuid", "")[:8]
    role = ""
    preview = ""

    if t in ("user", "assistant"):
        msg = obj.get("message", {})
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    preview = block["text"][:120].replace("\n", " ")
                    break
                if block.get("type") == "tool_use":
                    preview = f"[tool: {block.get('name', '?')}]"
                    break
                if block.get("type") == "tool_result":
                    preview = f"[tool_result: {str(block.get('content', ''))[:80]}]"
                    break
        elif isinstance(content, str):
            preview = content[:120].replace("\n", " ")

    return uid, f"{t:10s} | {role:10s} | {uid} | {preview}"


def text_from_codex_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return " ".join(parts)


def preview_codex(obj: dict) -> tuple[str, str]:
    t = obj.get("type", "?")
    payload = obj.get("payload", {})
    if not isinstance(payload, dict):
        return "", f"{t:13s} | {'':10s} | {'':8s} |"

    uid = record_id(obj, "codex")[:8]
    role = ""
    preview = ""

    if t == "session_meta":
        role = "summary"
        preview = f"session {payload.get('id', '?')} cwd={payload.get('cwd', '?')}"
    elif t == "turn_context":
        role = "summary"
        preview = f"turn {payload.get('turn_id', '?')} cwd={payload.get('cwd', '?')}"
    elif t == "event_msg":
        role = payload.get("type", "")
        preview = str(payload.get("message", payload.get("info", "")))[:120].replace("\n", " ")
    elif t == "response_item":
        ptype = payload.get("type", "?")
        if ptype == "message":
            role = payload.get("role", "")
            preview = text_from_codex_content(payload.get("content", ""))[:120].replace("\n", " ")
        elif ptype == "function_call":
            role = "tool_call"
            preview = f"[tool: {payload.get('name', '?')}]"
        elif ptype == "function_call_output":
            role = "tool_result"
            preview = str(payload.get("output", ""))[:120].replace("\n", " ")
        else:
            role = ptype

    return uid, f"{t:13s} | {role:10s} | {uid} | {preview}"


def analyze_session(lines: list[str], agent: str) -> None:
    """Print a summary of the session messages for choosing a cutpoint."""
    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            if agent == "codex":
                _, row = preview_codex(obj)
                if obj.get("type") in ("session_meta", "turn_context", "event_msg", "response_item"):
                    print(f"  L{i+1:4d} | {row}")
            else:
                _, row = preview_claude(obj)
                if obj.get("type") in ("user", "assistant"):
                    print(f"  L{i+1:4d} | {row}")
        except json.JSONDecodeError:
            continue


def rewrite_session_id(obj: dict, agent: str, new_session_id: str, original_session_id: str | None) -> tuple[dict, str | None]:
    if agent == "codex":
        payload = obj.get("payload")
        if obj.get("type") == "session_meta" and isinstance(payload, dict):
            original_session_id = original_session_id or str(payload.get("id", ""))
            payload["id"] = new_session_id
        return obj, original_session_id

    if original_session_id is None and "sessionId" in obj:
        original_session_id = obj["sessionId"]
    if "sessionId" in obj:
        obj["sessionId"] = new_session_id
    return obj, original_session_id


def forged_filename(agent: str, source: Path, new_session_id: str) -> str:
    if agent == "codex":
        return f"rollout-forged-{new_session_id}.jsonl"
    return f"{new_session_id}.jsonl"


def forge(
    session_path: str,
    cutpoint: str,
    output_dir: str,
    project_dir: str | None = None,
    analyze: bool = False,
    agent: AgentKind = "auto",
) -> dict:
    """Forge a truncated session. Returns metadata about the forged session."""
    source_path = Path(session_path)
    with open(source_path) as f:
        lines = f.readlines()

    detected_agent = detect_agent(lines, agent)
    if analyze:
        print(f"{detected_agent.title()} session messages:")
        analyze_session(lines, detected_agent)
        return {}

    cut_idx = find_cutpoint(lines, cutpoint, detected_agent)
    truncated = lines[:cut_idx]

    new_session_id = str(uuid.uuid4())

    forged_lines = []
    original_session_id = None
    for line in truncated:
        try:
            obj = json.loads(line)
            obj, original_session_id = rewrite_session_id(obj, detected_agent, new_session_id, original_session_id)
            forged_lines.append(json.dumps(obj) + "\n")
        except json.JSONDecodeError:
            forged_lines.append(line)

    # Write forged session
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    filename = forged_filename(detected_agent, source_path, new_session_id)
    forged_file = out_path / filename
    with open(forged_file, "w") as f:
        f.writelines(forged_lines)

    # Also copy to project dir if specified
    project_file_path: str | None = None
    if project_dir:
        proj_path = Path(project_dir)
        proj_path.mkdir(parents=True, exist_ok=True)
        proj_file = proj_path / filename
        with open(proj_file, "w") as f:
            f.writelines(forged_lines)
        project_file_path = str(proj_file)

    metadata = {
        "agent": detected_agent,
        "forged_session_id": new_session_id,
        "original_session_id": original_session_id,
        "original_lines": len(lines),
        "truncated_at_line": cut_idx,
        "forged_lines": len(forged_lines),
        "forged_file": str(forged_file),
        "project_file": project_file_path,
    }

    return metadata


def main():
    parser = argparse.ArgumentParser(description="Forge a truncated Claude Code or Codex session for replay")
    parser.add_argument("session_file", help="Path to the original session JSONL")
    parser.add_argument("cutpoint", nargs="?", help="Line number or UUID prefix to cut after")
    parser.add_argument("output_dir", nargs="?", default=".", help="Directory for forged session")
    parser.add_argument("--agent", choices=["auto", "claude", "codex"], default="auto")
    parser.add_argument("--project-dir", help="Agent session dir to copy forged session into")
    parser.add_argument("--analyze", action="store_true", help="Print session structure and exit")
    args = parser.parse_args()

    if args.analyze or not args.cutpoint:
        forge(args.session_file, "", "", analyze=True, agent=args.agent)
        return

    result = forge(args.session_file, args.cutpoint, args.output_dir, args.project_dir, agent=args.agent)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
