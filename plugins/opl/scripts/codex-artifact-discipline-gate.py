"""Check text introduced by an artifact edit before the tool executes."""
from pathlib import Path
import sys

from codex_discipline_policy import DisciplinePolicy, has_bypass, read_input, read_text


def main():
    hook_input = read_input()
    tool_input = hook_input.get('tool_input') or {}
    patch = tool_input.get('patch', '')
    additions = '\n'.join(line[1:] for line in patch.splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
    text = '\n'.join((tool_input.get('new_string', ''), tool_input.get('content', ''), additions))
    path = tool_input.get('file_path', '')
    if not text.strip() or has_bypass(text):
        return 0
    if path and Path(path).is_file() and has_bypass(read_text(path)):
        return 0
    policy = DisciplinePolicy(hook_input)
    mvp_hits, deferrals = policy.scan(text)
    if not mvp_hits and not deferrals:
        return 0
    print(policy.report('edit', f'your edit to: {path}', mvp_hits, deferrals), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
