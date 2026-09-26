"""List Codex JSONL session logs newest first, with an optional mtime cutoff."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--newer-than-log', metavar='codex-session-log.jsonl')
    args = parser.parse_args()
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    sessions = home / 'sessions'
    if not sessions.is_dir():
        print(f'Codex session directory does not exist: {sessions}', file=sys.stderr)
        return 1
    cutoff = None
    if args.newer_than_log:
        source = Path(args.newer_than_log).expanduser()
        if not source.is_file():
            print(f'newer-than log does not exist: {source}', file=sys.stderr)
            return 1
        cutoff = source.stat().st_mtime_ns
    logs = []
    for directory, _, files in os.walk(sessions, onerror=raise_walk_error):
        for name in files:
            if not name.endswith('.jsonl'):
                continue
            path = Path(directory) / name
            modified = path.stat().st_mtime_ns
            if cutoff is None or modified > cutoff:
                logs.append((modified, str(path)))
    for _, path in sorted(logs, reverse=True):
        print(path)
    return 0


def raise_walk_error(error):
    raise error


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', newline='\n')
    try:
        sys.exit(main())
    except OSError as error:
        print(f'Failed to list Codex session logs: {error}', file=sys.stderr)
        sys.exit(1)
