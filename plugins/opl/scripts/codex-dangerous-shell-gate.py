"""Conservative destructive-command guard for POSIX and PowerShell commands.

This recognizes common command shapes; it is not a complete shell parser.
"""
import re
import sys

from codex_discipline_policy import read_input


def unsafe_command(command):
    normalized = command.replace('`\n', ' ').replace('\\\n', ' ').replace('\n', ' ')
    boundaries = r'''(?:^|[\s;|&"'])'''
    for pattern, reason in (
        (r'git\s+push\b[^;|&]*\s(?:--force(?:-with-lease)?|-f)(?=[\s;|&]|$)', 'force-push requires explicit human handling'),
        (r'git\s+reset\s+--hard(?=[\s;|&]|$)', 'git reset --hard is destructive'),
        (r'(?:wget|curl)(?:\.exe)?\s+', 'raw downloader command is not auto-allowed'),
        (r'(?:Invoke-WebRequest|Invoke-RestMethod|iwr|irm)\s+', 'raw downloader command is not auto-allowed'),
    ):
        match = re.search(boundaries + pattern, normalized, re.I)
        if match:
            return reason, match.group().strip()
    for match in re.finditer(boundaries + r'(rm|Remove-Item|ri|del|erase|rmdir|rd)\s+([^;|&]*)', normalized, re.I):
        command_name = match.group(1).lower()
        segment = match.group().strip()
        # Keep quoted paths as single arguments and keep Windows separators.
        tokens = [token.strip('"\'') for token in re.findall(r'"[^"]*"|\'[^\']*\'|[^\s,]+', match.group(2))]
        if '--no-preserve-root' in tokens:
            return 'rm --no-preserve-root is never safe for agent automation', segment
        recursive = any(re.fullmatch(r'-[A-Za-z]*r[A-Za-z]*|--recursive', token) for token in tokens)
        recursive = recursive or any(token.lower() in ('-recurse', '/s') for token in tokens)
        if command_name in ('remove-item', 'ri', 'del', 'erase'):
            recursive = recursive or any(re.fullmatch(r'-rec(?:u(?:r(?:s(?:e)?)?)?)?', token, re.I) for token in tokens)
        for token in tokens:
            path = token.replace('\\', '/')
            if re.search(r'(?:^|/)\.\.(?:/|$)', path):
                return 'removal targeting a parent directory is blocked', segment
            if not recursive:
                continue
            if re.match(r'^(?:~|\$HOME|\$\{HOME\}|\$env:USERPROFILE|\$env:HOMEPATH|%USERPROFILE%)(?:/|$)', path, re.I):
                return 'recursive removal targets parent/root/home scope', segment
            if path in ('.', './', '/', '/*', '*') or re.fullmatch(r'[A-Za-z]:/?\*?', path):
                return 'recursive removal targets current/root directory scope', segment
            if re.fullmatch(r'//[^/]+/[^/]+/?\*?', path):
                return 'recursive removal targets a share root', segment
            if path.endswith('/*'):
                return 'recursive removal with path glob is too easy to mis-scope', segment
    return None


def main():
    tool_input = read_input().get('tool_input') or {}
    result = unsafe_command(tool_input.get('command', tool_input.get('cmd', '')))
    if not result:
        return 0
    reason, match = result
    print(f'''[dangerous-shell-gate] BLOCK: {reason}

Matched:
  {match}

Use a narrower, quoted target or perform this manually after reviewing it.
For destructive cleanup inside the repo, prefer explicit paths, for example:
  Remove-Item -LiteralPath './path/to/generated-dir' -Recurse -Force

This gate is intentionally conservative around recursive removal, parent
directory traversal, root/home targets, and destructive git history commands.''', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
