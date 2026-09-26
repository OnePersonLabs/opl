"""Require the native dollar sigil for known skills on instruction surfaces."""
import os
from pathlib import Path
import re
import sys

from codex_discipline_policy import read_input, read_text


BYPASS = '<!-- skill-reference-sigil-bypass -->'
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')


def normalize(path):
    return str(path).replace('\\', '/')


def scan_surface(path, home, codex_home):
    if path in ('AGENTS.md', '.codex/hooks.json', '.codex/config.toml'):
        return True
    patterns = (
        r'\.agents/references/.+\.md', r'\.agents/skills/[^/]+/SKILL\.md',
        r'\.agents/skills/[^/]+/agents/[^/]+\.(?:ya?ml|json|toml)',
        r'\.agents/skills/[^/]+/references/.+\.md',
        r'\.agents/skills/[^/]+/scripts/[^/]+\.(?:mjs|js|sh|py|ps1)',
        r'scripts/[^/]+\.(?:mjs|js|sh|py|ps1)',
    )
    return any(re.fullmatch(pattern, path) for pattern in patterns) or any(
        path.startswith(normalize(root).rstrip('/') + '/')
        for root in (home / '.agents/skills', codex_home / 'skills'))


def skill_names(roots):
    names = set()
    for root in roots:
        if not root.is_dir():
            continue
        for directory, folders, files in os.walk(root):
            depth = len(Path(directory).relative_to(root).parts)
            if depth >= 3:
                folders[:] = []
            if 'SKILL.md' not in files:
                continue
            path = Path(directory) / 'SKILL.md'
            name = path.parent.name
            lines = read_text(path).splitlines()
            if lines and lines[0] == '---':
                for line in lines[1:]:
                    if line == '---':
                        break
                    if line.startswith('name:'):
                        candidate = line[5:].strip().strip('"\'')
                        if NAME.fullmatch(candidate):
                            name = candidate
                        break
            if NAME.fullmatch(name):
                names.add(name)
    return sorted(names)


def main():
    tool_input = read_input().get('tool_input') or {}
    file_path = tool_input.get('file_path')
    if not file_path or not Path(file_path).is_file():
        return 0
    project = Path(os.environ.get('CODEX_PROJECT_DIR', os.getcwd())).resolve()
    path = Path(file_path).resolve()
    try:
        relative = normalize(path.relative_to(project))
    except ValueError:
        relative = normalize(path)
    full_path = normalize(path)
    if any(re.search(r'(?:^|/)\.agents/skills/openspec-[^/]+/SKILL\.md$', value) for value in (relative, full_path)):
        return 0
    home = Path(os.environ.get('HOME') or Path.home())
    codex_home = Path(os.environ.get('CODEX_HOME', home / '.codex'))
    if not any(scan_surface(value, home, codex_home) for value in (relative, full_path)):
        return 0
    text = read_text(path)
    if '\0' in text or not re.search(r'`[a-z0-9][a-z0-9-]*-[a-z0-9][a-z0-9-]*(?:\s[^`]*)?`', text):
        return 0
    plugin = Path(os.environ.get('PLUGIN_ROOT', Path(__file__).resolve().parent.parent))
    roots = [plugin / 'skills', project / '.agents/skills', codex_home / 'skills', home / '.agents/skills']
    if os.name != 'nt':
        roots.append(Path('/etc/codex/skills'))
    names = skill_names(roots)
    if not names:
        return 0
    pattern = re.compile(r'`(?:' + '|'.join(re.escape(name) for name in names) + r')(?:\s[^`]*)?`')
    hits = [f'  {number}:{line}' for number, line in enumerate(text.splitlines(), 1)
            if BYPASS not in line and pattern.search(line)]
    if not hits:
        return 0
    formatted = '\n'.join(hits[:20])
    print(f'''[skill-reference-sigil-gate] This edit left backtick-wrapped Agent Skill names in:

  {file_path}

Matches:
{formatted}

If these are skill references or invocations, use the native dollar-sigil form
instead, e.g. $<skill-name>.

If a match is intentionally a literal non-skill token, add this same-line bypass
comment and leave the text unchanged:
  {BYPASS}''', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
