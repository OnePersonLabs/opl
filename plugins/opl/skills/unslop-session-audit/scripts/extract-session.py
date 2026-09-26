#!/usr/bin/env python3
"""
Extract a Claude Code or Codex session JSONL into a compact, behavior-only
transcript for unslop-session-audit analysis.

The raw JSONL can be 10K+ lines and includes full tool I/O -- loading it into an
analysis context is wasteful and noisy. This produces a numbered turn-by-turn
transcript carrying only the behavioral signal: what the user said, what the agent
said, which tools it called (name + a slice of input), and a slice of each result.
Long fields are truncated to first/last 100 chars so structure survives without bulk.

Usage:
    python3 extract-session.py <session.jsonl> [--agent auto|claude|codex] [--out <path>] [--max-kb <N>]

    --out:    output path (default: unslop-session-<session-uuid>.txt in the system temporary directory)
    --max-kb: soft cap on output size in KB (default 50). When exceeded, earlier
              turns are dropped (the recent tail is where redirects and fixes cluster)
              and a NOTICE records how many were elided -- never a silent truncation.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Literal

USER_TRUNC = 500
TOOL_INPUT_TRUNC = 200
TOOL_RESULT_TRUNC = 200
LONG_FIELD = 300  # above this, keep first/last 100 with an elision marker
AgentKind = Literal["auto", "claude", "codex"]


def clip(text: str, limit: int) -> str:
    """Collapse newlines and truncate. Long fields keep head+tail, not just head."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    if len(text) > LONG_FIELD:
        return f"{text[:100]} ...[{len(text) - 200} chars elided]... {text[-100:]}"
    return text[:limit] + " ..."


def render_block(block: dict) -> str | None:
    """Render one assistant content block as a transcript line, or None to skip."""
    btype = block.get("type")
    if btype == "text":
        t = block.get("text", "").strip()
        return clip(t, LONG_FIELD) if t else None
    if btype == "tool_use":
        name = block.get("name", "?")
        inp = json.dumps(block.get("input", {}), ensure_ascii=False)
        return f"[TOOL: {name}] input: {clip(inp, TOOL_INPUT_TRUNC)}"
    if btype == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
            )
        return f"[TOOL_RESULT] {clip(content, TOOL_RESULT_TRUNC)}"
    return None


def text_from_codex_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def render_claude_turn(obj: dict) -> tuple[str, list[str]] | None:
    """Return (role, lines) for a renderable Claude turn, or None to skip."""
    ttype = obj.get("type")
    if ttype == "summary":
        return "summary", [clip(obj.get("summary", ""), LONG_FIELD)]

    if ttype not in ("user", "assistant"):
        return None

    msg = obj.get("message", {})
    content = msg.get("content", "")
    lines: list[str] = []

    if isinstance(content, str):
        limit = USER_TRUNC if ttype == "user" else LONG_FIELD
        if content.strip():
            lines.append(clip(content, limit))
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            # user-side tool_result blocks carry the tool output the agent saw
            if ttype == "user" and block.get("type") == "tool_result":
                rendered = render_block(block)
            else:
                rendered = render_block(block)
            if rendered:
                lines.append(rendered)

    return (ttype, lines) if lines else None


def render_codex_turn(obj: dict) -> tuple[str, list[str]] | None:
    """Return (role, lines) for a renderable Codex rollout record, or None to skip."""
    rtype = obj.get("type")
    payload = obj.get("payload", {})
    if not isinstance(payload, dict):
        return None

    if rtype == "session_meta":
        session_id = payload.get("id", "?")
        cwd = payload.get("cwd", "?")
        source = payload.get("source") or payload.get("originator") or "codex"
        return "summary", [clip(f"Codex session {session_id} cwd={cwd} source={source}", LONG_FIELD)]

    if rtype == "turn_context":
        cwd = payload.get("cwd", "?")
        model = payload.get("model", "?")
        return "summary", [clip(f"Turn context cwd={cwd} model={model}", LONG_FIELD)]

    if rtype == "event_msg":
        return None

    if rtype != "response_item":
        return None

    ptype = payload.get("type")
    if ptype == "message":
        role = payload.get("role", "message")
        if role not in ("user", "assistant", "summary"):
            return None
        text = text_from_codex_content(payload.get("content", ""))
        limit = USER_TRUNC if role == "user" else LONG_FIELD
        return (role, [clip(text, limit)]) if text.strip() else None

    if ptype == "function_call":
        name = payload.get("name", "?")
        args = payload.get("arguments", "")
        return "assistant", [f"[TOOL: {name}] input: {clip(args, TOOL_INPUT_TRUNC)}"]

    if ptype == "function_call_output":
        output = payload.get("output", "")
        return "tool_result", [f"[TOOL_RESULT] {clip(output, TOOL_RESULT_TRUNC)}"]

    return None


def detect_agent(src: Path, requested: AgentKind) -> Literal["claude", "codex"]:
    if requested != "auto":
        return requested

    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") in ("response_item", "event_msg", "session_meta", "turn_context"):
                return "codex"
            if obj.get("type") in ("user", "assistant", "summary") or "sessionId" in obj or "uuid" in obj:
                return "claude"

    return "claude"


def session_name(src: Path, agent: str) -> str:
    if agent == "codex" and src.stem.startswith("rollout-"):
        return src.stem.removeprefix("rollout-")
    return src.stem


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a session JSONL into a compact transcript")
    parser.add_argument("session_file")
    parser.add_argument("--agent", choices=["auto", "claude", "codex"], default="auto")
    parser.add_argument("--out")
    parser.add_argument("--max-kb", type=int, default=50)
    args = parser.parse_args()

    src = Path(args.session_file)
    if not src.is_file():
        print(f"Session file not found: {src}", file=sys.stderr)
        sys.exit(1)

    agent = detect_agent(src, args.agent)
    session_uuid = session_name(src, agent)
    out_path = Path(args.out) if args.out else Path(tempfile.gettempdir()) / f"unslop-session-{session_uuid}.txt"

    rendered_turns: list[str] = []
    turn_no = 0
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            result = render_codex_turn(obj) if agent == "codex" else render_claude_turn(obj)
            if result is None:
                continue
            role, lines = result
            turn_no += 1
            body = "\n".join(lines)
            rendered_turns.append(f"=== TURN {turn_no} [{role}] ===\n{body}\n")

    # Soft size cap: drop oldest turns first (redirects/fixes cluster in the tail).
    max_bytes = args.max_kb * 1024
    dropped = 0
    while rendered_turns and sum(len(t.encode()) for t in rendered_turns) > max_bytes:
        rendered_turns.pop(0)
        dropped += 1

    header = f"# {agent.title()} session {session_uuid} -- {turn_no} turns"
    if dropped:
        header += f"\n# NOTICE: {dropped} oldest turns elided to fit {args.max_kb}KB cap (analyze the tail)"

    out_path.write_text(header + "\n\n" + "\n".join(rendered_turns), encoding="utf-8")
    print(json.dumps({
        "out": str(out_path),
        "agent": agent,
        "total_turns": turn_no,
        "emitted_turns": len(rendered_turns),
        "dropped_oldest": dropped,
        "size_kb": round(out_path.stat().st_size / 1024, 1),
    }, indent=2))


if __name__ == "__main__":
    main()
