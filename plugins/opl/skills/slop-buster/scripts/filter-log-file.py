"""Emit candidate Codex messages with their physical source-line anchors."""
import argparse
import os
from pathlib import Path
import re
import sys


# Keep the existing candidate patterns. Input is untrusted text, never code;
# retain raw records so reviewers can recover the exact source-line context.
USER_RECORD = re.compile(r'"type":"(?:response_item|event_msg)","payload":\{(?:"type":"message","role":"user"|"type":"user_message","message":)')
ASSISTANT_RECORD = re.compile(r'"type":"(?:response_item|event_msg)","payload":\{(?:"type":"message","id":"msg_[^"]+","role":"assistant"|"type":"agent_message","message":)')
BOOTSTRAP_USER = re.compile(r'"(?:# AGENTS\.md instructions for |<environment_context>|<skill>\\n<name>|<INSTRUCTIONS>|--- project-doc ---)')
AGENT_SIGNAL = re.compile(r'\b(?:abort|blocked|caught|clean|commit|correction|dirty|error|fail(?:ed|ing|ure)?|fix(?:ed|ing)?|miss(?:ed|ing)?|mistake|push(?:ed|ing)?|recover(?:ed|y)?|rerun(?:ning)?|retry(?:ing)?|slop|stale|validat(?:e|ed|ion)|wrong)\b', re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log_file', metavar='codex-session-log.jsonl')
    args = parser.parse_args()
    path = Path(args.log_file).expanduser()
    if not path.is_file():
        print(f'Codex session log does not exist: {path}', file=sys.stderr)
        return 1
    raw_limit = os.environ.get('SLOP_BUSTER_MAX_OUTPUT_CHARS') or '2500'
    if not re.fullmatch(r'[1-9][0-9]*', raw_limit):
        print(f'SLOP_BUSTER_MAX_OUTPUT_CHARS must be a positive integer: {raw_limit}', file=sys.stderr)
        return 2
    limit = int(raw_limit)
    with path.open(encoding='utf-8', newline='') as stream:
        print(f'SLOP_BUSTER_CANDIDATE_START\tlogPath={path}\tmaxOutputChars={limit}')
        emitted = 0
        for number, line in enumerate(stream, 1):
            user = USER_RECORD.search(line) and not BOOTSTRAP_USER.search(line)
            assistant = ASSISTANT_RECORD.search(line) and AGENT_SIGNAL.search(line)
            if not user and not assistant:
                continue
            emitted += 1
            truncated = len(line) > limit
            output = line[:limit].rstrip('\r\n')
            print(f'[{number}] truncated={str(truncated).lower()} {output}')
        print(f'SLOP_BUSTER_CANDIDATE_END\tlinesEmitted={emitted}')
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', newline='\n')
    try:
        sys.exit(main())
    except (OSError, UnicodeError) as error:
        print(f'Failed to read Codex session log: {error}', file=sys.stderr)
        sys.exit(1)
