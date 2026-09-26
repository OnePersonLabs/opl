"""Check the latest assistant response when a session stops."""
import os
import re

from codex_discipline_policy import DisciplinePolicy, emit_json, has_bypass, last_assistant_text, read_input


def main():
    hook_input = read_input()
    try:
        tail_lines = max(1, int(os.environ.get('DISCIPLINE_TRANSCRIPT_TAIL_LINES', '200')))
    except ValueError:
        tail_lines = 200
    text = last_assistant_text(hook_input.get('transcript_path'), tail_lines)
    if not text or has_bypass(text):
        emit_json({'continue': True})
        return
    lines, in_fence = [], False
    for line in text.splitlines():
        if re.match(r'^\s*```', line):
            in_fence = not in_fence
        elif not in_fence:
            lines.append(line)
    policy = DisciplinePolicy(hook_input)
    mvp_hits, deferrals = policy.scan('\n'.join(lines))
    emit_json({'decision': 'block', 'reason': policy.report('response', 'your last response', mvp_hits, deferrals)}
              if mvp_hits or deferrals else {'continue': True})


if __name__ == '__main__':
    main()
