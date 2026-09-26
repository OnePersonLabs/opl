"""Durable-deferral provider for repositories that use GitHub Issues."""
import json
import os
from pathlib import Path
import re
import subprocess

from codex_discipline_policy import emit_json, read_input, run_cli


def handle(payload):
    content, root = payload.get('content', ''), payload.get('repository_root', '')
    if payload.get('protocol_version') != 1 or not content or not root:
        return {'handled': False}
    refs = set(re.findall(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[0-9]+', content))
    refs.update(re.findall(r'(?<![\w])#[0-9]+', content))
    if not refs:
        return {'handled': False}

    def reject(reason):
        return {'handled': False, 'recognized': True, 'reason': reason}

    if not Path(root).is_dir():
        return reject(f'GitHub issue deferral repository root is unavailable: {root}')
    for ref in sorted(refs):
        try:
            result = run_cli(os.environ.get('GH_BIN', 'gh'),
                             ['issue', 'view', ref.lstrip('#'), '--json', 'number,state,url'], cwd=root, timeout=5)
        except FileNotFoundError:
            return reject('GitHub issue deferral requires the gh CLI')
        except (OSError, subprocess.TimeoutExpired):
            return reject(f'GitHub issue {ref} could not be verified')
        if result.returncode != 0:
            return reject(f'GitHub issue {ref} could not be verified')
        try:
            issue = json.loads(result.stdout)
        except json.JSONDecodeError:
            return reject(f'GitHub issue {ref} returned an invalid response')
        state = issue.get('state') if isinstance(issue, dict) else None
        if state != 'OPEN':
            return reject(f'GitHub issue {ref} is {state} and cannot own deferred work' if state
                          else f'GitHub issue {ref} returned an invalid response')
    return {'handled': True, 'handler': 'github-issues'}


if __name__ == '__main__':
    emit_json(handle(read_input()))
