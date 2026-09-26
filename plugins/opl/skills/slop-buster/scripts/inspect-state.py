"""Report generated slop state without creating or changing any files."""
import os
from pathlib import Path
import sys


def main():
    codex_home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    state = Path(os.environ.get('SLOP_BUSTER_STATE_DIR') or codex_home / 'slop-buster').expanduser()
    print(f'stateDir\t{state}')
    entries = list(state.iterdir()) if state.is_dir() else []
    print(f'hasFiles\t{str(bool(entries)).lower()}')
    slop_files = [path for path in entries if path.is_file() and path.match('slop-*.md')]
    latest = max(slop_files, key=lambda path: (path.stat().st_mtime_ns, str(path)), default=None)
    print(f'latestSlopFile\t{latest or ""}')
    source = ''
    if latest:
        with latest.open(encoding='utf-8-sig') as stream:
            source = next((line.removeprefix('SOURCE_LOG: ').rstrip('\r\n')
                           for line in stream if line.startswith('SOURCE_LOG: ')), '')
    print(f'latestSourceLog\t{source}')
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', newline='\n')
    try:
        sys.exit(main())
    except (OSError, UnicodeError) as error:
        print(f'Failed to inspect slop state: {error}', file=sys.stderr)
        sys.exit(1)
