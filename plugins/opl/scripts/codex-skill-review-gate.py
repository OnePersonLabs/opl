"""Prompt for a completed instruction review when the editing turn ends."""
import hashlib
import os
from pathlib import Path
import re

from codex_discipline_policy import emit_json, read_input


PATCH_PATH = re.compile(r'^\*\*\* (?:Add|Update|Delete) File:[ \t]*([^\r\n]+)', re.M)


def instruction_file(path):
    return isinstance(path, str) and path.replace('\\', '/').rsplit('/', 1)[-1].lower() in ('skill.md', 'agents.md')


def edited_paths(tool_name, tool_input):
    name = str(tool_name).split('.')[-1].lower()
    if name in ('edit', 'write'):
        path = tool_input.get('file_path')
        return {path} if instruction_file(path) else set()
    if name in ('applypatch', 'apply_patch'):
        patch = tool_input.get('patch') or tool_input.get('command') or ''
        if isinstance(patch, str):
            return {path.strip() for path in PATCH_PATH.findall(patch) if instruction_file(path.strip())}
    return set()


def pending_file(hook):
    session = hook.get('session_id')
    turn = hook.get('turn_id')
    if not isinstance(session, str) or not session or not isinstance(turn, str) or not turn:
        return None
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    key = hashlib.sha256(f'{session}\0{turn}'.encode('utf-8')).hexdigest()
    return home / 'tmp' / 'opl-agent-instructions-review' / key


def decision(hook):
    pending = pending_file(hook)
    if hook.get('hook_event_name') == 'Stop':
        if pending is None or not pending.is_file():
            return {'continue': True}
        pending.unlink()
        return {
            'decision': 'block',
            'reason': (
                'Review this instruction change with $opl:agent-instructions before finishing; '
                'skip it if you already did.'
            ),
        }
    if hook.get('hook_event_name') != 'PostToolUse' or pending is None:
        return {'continue': True}
    tool_input = hook.get('tool_input')
    if not isinstance(tool_input, dict):
        return {'continue': True}
    response = hook.get('tool_response')
    if isinstance(response, dict) and (response.get('isError') is True or response.get('exit_code') not in (None, 0)):
        return {'continue': True}
    paths = edited_paths(hook.get('tool_name'), tool_input)
    if not paths:
        return {'continue': True}
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.touch()
    return {'continue': True}


if __name__ == '__main__':
    emit_json(decision(read_input()))
