"""Native shared policy for OPL hooks and domain-owned deferral providers.

<!-- discipline-bypass -->
The literal patterns below are policy examples, not product deferrals.
"""

from collections import deque
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


BANNED_PHRASES = (
    'future change', 'out of scope', 'deliberate accepted cost', 'we will need to',
    'later we can', 'deferred', 'defer', 'accept the gap', 'accept the slight',
    'accept the small', 'accept the aspirational', 'accept the cosmetic',
    'left for user judgment', "for now we'll just", 'good enough for v1',
    'good enough for now', 'we can revisit this', 'tactical fix only',
    'minimum viable fix', "cost of fixing isn't worth", 'ship now, fix later',
    'not worth the dance', 'trivial enough to skip', 'file follow-up if load-bearing',
    'workaround keys on', 'work around by keying', 'proves insufficient post-merge',
    'structural and pre-existing', 'left intact', 'intentionally left',
    'future-work guidance', 'future-work item', 'future-work items',
    'will be revisited', 'revisit later', 'revisited later', 'revisited when',
    'not in scope for this turn', 'not worth pre-editing', 'not worth touching now',
    'when those changes actually reach', 'when that change gets to',
    'conservative scope', 'leave them as-is', 'leave it for later',
    'leave that for later', 'will be moot', 'become moot', 'authored intentionally as',
    'historical record', 'no urgency', 'not enforcement', 'not blocking anything',
)
PRE_EXISTING_DISMISSAL = re.compile(
    r'pre-existing.*(bug|issue|limitation|problem|defect|skip|not (addressing|fix))'
    r'|pre-existing\.\s*$|pre-existing[,]', re.I,
)
# Keep effort estimates hyphenated so temporal prose such as "20 minutes later"
# is not confused with trivializing deferred work. Change patterns only after
# sampling recent session hits and checking both missed cases and false positives.
TRIVIALIZING_DEFER = re.compile(
    r'([0-9]+-(min|minute|hr|hour)s?|quick|trivial|tiny|easy)[^.!?]{0,40}'
    r'(later|eventually|down the (road|line)|another (time|session)|some other time'
    r'|circle back|when i (get|come) (around|to|back))', re.I,
)
FOLLOWUP = re.compile(r'follow-up|follow up|pending |blocked on|awaiting |should\s+file|future work', re.I)
LEAVING_WORK_UNRESOLVED = re.compile(
    r'\b(?:leave|leaving|left)\s+(?:it|that|them|those|these)\s+alone\b'
    r'|\b(?:leave|leaving|left)\b[^.!?\n]{0,100}'
    r'\b(?:issues?|failures?|errors?|bugs?|defects?|problems?|work)\b'
    r'[^.!?\n]{0,40}\b(?:alone|unresolved|unaddressed|unfixed)\b', re.I,
)
PLACEHOLDER = re.compile(r'(?<![A-Za-z0-9_])(TODO|FIXME)(?![A-Za-z0-9_])')
SENTINELS = ('<!-- discipline-bypass -->', '<!-- mvp-meta -->', '<!-- deferral-meta -->')


def read_input():
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def emit_json(value):
    print(json.dumps(value, ensure_ascii=True))


def read_text(path):
    return Path(path).read_text(encoding='utf-8-sig', errors='replace')


def has_bypass(text):
    return any(sentinel in text for sentinel in SENTINELS)


def cli_command(binary):
    """Resolve one executable path, never a shell expression or command string."""
    resolved = shutil.which(binary) or binary
    path = Path(resolved)
    if path.suffix.lower() == '.py':
        return [sys.executable, '-B', '-X', 'utf8', str(path)]
    if path.suffix.lower() in ('.js', '.mjs', '.cjs'):
        return [os.environ.get('NODE_BIN', 'node'), str(path)]
    if os.name == 'nt' and path.suffix.lower() in ('.cmd', '.bat', '.ps1'):
        # npm's Codex shims are batch files on Windows. Invoke their known JS
        # owner directly so paths and JSON never pass through cmd.exe parsing.
        if path.stem.lower() == 'codex':
            for entry in (
                path.parent.parent / '@openai/codex/bin/codex.js',
                path.parent / 'node_modules/@openai/codex/bin/codex.js',
                path.parent / 'bin/codex.js',
            ):
                if entry.is_file():
                    return [os.environ.get('NODE_BIN', 'node'), str(entry)]
        raise OSError(f'Native executable required; cannot safely run shell shim: {path}')
    return [str(path)]


def run_cli(binary, args, **kwargs):
    return subprocess.run(cli_command(binary) + list(args), text=True,
                          encoding='utf-8', errors='replace', capture_output=True,
                          check=False, **kwargs)


def enabled_plugin_roots(data):
    """Support marketplace source entries and Codex installed-cache entries."""
    entries = data.get('installed', []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    roots = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('enabled') is not True:
            continue
        if entry.get('installed') is False:
            continue
        source = entry.get('source') or {}
        for root in (entry.get('installedPath'), source.get('path') if isinstance(source, dict) else None):
            if isinstance(root, str) and root:
                roots.add(root)
                break
    return sorted(roots)


class DisciplinePolicy:
    def __init__(self, hook_input):
        self.input = hook_input
        self.repository_root = os.environ.get('CODEX_PROJECT_DIR', os.getcwd())
        self.plugin_root = Path(os.environ.get('OPL_DISCIPLINE_PLUGIN_ROOT', Path(__file__).resolve().parent.parent))
        self.transcript = hook_input.get('transcript_path', '')
        self.exceptions_file = self.plugin_root / 'scripts/codex-discipline-gate.exceptions.txt'
        if not self.exceptions_file.is_file():
            self.exceptions_file = Path(self.repository_root) / 'scripts/codex-discipline-gate.exceptions.txt'
        self.exceptions = []
        if self.exceptions_file.is_file():
            self.exceptions = [line.strip().lower() for line in read_text(self.exceptions_file).splitlines()
                               if line.strip() and not line.lstrip().startswith('#')]
        self.handlers = None
        self.resolutions = {}

    def load_handlers(self):
        if 'DISCIPLINE_DEFERRAL_HANDLERS' in os.environ:
            return [Path(path) for path in os.environ['DISCIPLINE_DEFERRAL_HANDLERS'].splitlines()
                    if path and Path(path).is_file()]
        try:
            result = run_cli(os.environ.get('CODEX_BIN', 'codex'), ['plugin', 'list', '--json'], timeout=5)
            if result.returncode:
                return []
            roots = enabled_plugin_roots(json.loads(result.stdout))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return []
        return sorted({handler for root in roots for handler in (Path(root) / 'scripts').glob('codex-*-deferral-handler.py')
                       if handler.is_file()})

    def resolve_deferral(self, content):
        if content in self.resolutions:
            return self.resolutions[content]
        if self.handlers is None:
            self.handlers = self.load_handlers()
        detail = 'no installed deferral handler accepted this line'
        payload = json.dumps({'protocol_version': 1, 'content': content,
                              'repository_root': self.repository_root, 'transcript_path': self.transcript})
        try:
            timeout = max(0.01, float(os.environ.get('DISCIPLINE_HANDLER_TIMEOUT_SECONDS', '5')))
        except ValueError:
            timeout = 5
        for handler in self.handlers:
            try:
                result = run_cli(str(handler), [], input=payload, timeout=timeout)
                output = json.loads(result.stdout)
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
                detail = f'deferral handler {handler.name} failed: {type(error).__name__}'
                continue
            if result.returncode != 0 or not isinstance(output, dict):
                detail = f'deferral handler {handler.name} returned an invalid response'
                continue
            if output.get('handled') is True:
                self.resolutions[content] = (True, '')
                return self.resolutions[content]
            if output.get('recognized') is True and output.get('reason'):
                detail = str(output['reason'])
        self.resolutions[content] = (False, detail)
        return self.resolutions[content]

    def is_excepted(self, content, needle):
        return any(entry in content.lower() and (not needle or needle.lower() in entry)
                   for entry in self.exceptions)

    def scan(self, text, prefix=''):
        mvp_hits, deferral_hits = [], []
        lines = list(enumerate(text.splitlines(), 1))
        for line, content in lines:
            for token in ('v1', 'v2', 'v3'):
                if re.search(r'(?<![A-Za-z0-9])' + token + r'(?![A-Za-z0-9])', content) and not self.is_excepted(content, token):
                    mvp_hits.append((prefix, line, content, token))

        def append(line, content, phrase):
            handled, detail = self.resolve_deferral(content)
            if not handled:
                deferral_hits.append((prefix, line, content, f'{phrase} ({detail})'))

        for phrase in BANNED_PHRASES:
            for line, content in lines:
                if phrase in content.lower() and not self.is_excepted(content, phrase):
                    append(line, content, phrase)
        for pattern, needle, phrase, exceptions in (
            (PRE_EXISTING_DISMISSAL, 'pre-existing', 'pre-existing (dismissal)', True),
            (TRIVIALIZING_DEFER, '', 'trivializing-defer', True),
            (PLACEHOLDER, '', 'TODO/FIXME placeholder', False),
            (FOLLOWUP, '', 'follow-up placeholder', False),
            (LEAVING_WORK_UNRESOLVED, '', 'leaving work unresolved', True),
        ):
            for line, content in lines:
                if pattern.search(content) and not (exceptions and self.is_excepted(content, needle)):
                    append(line, content, phrase)
        return mvp_hits, deferral_hits

    def report(self, mode, context, mvp_hits, deferral_hits):
        lines = [f'[discipline-gate / {mode}] BLOCK: {len(mvp_hits) + len(deferral_hits)} discipline issue(s) in {context}', '',
                 'The text quoted below was identified as potentially violating discipline',
                 'rules. Read each quote carefully -- this is the exact text the hook sees.',
                 'Some hits may be false positives, but most are real and need rewriting.']
        for title, hits, label, rule in (
            ('MVP framing', mvp_hits, 'token',
             'Rule: a single shipped product at a single quality bar. No phasing of architecture or quality-of-implementation across version labels.'),
            ('Deferral phrasing', deferral_hits, 'phrase',
             'Rule: every deferral or TODO-shaped placeholder must resolve to a durable tracked work item accepted by an installed domain handler. OPL is the final catch-all; workflow plugins own recognition and proof for their sinks. If no durable sink exists, complete the work or remove the claim.'),
        ):
            if hits:
                lines.extend(['', f'## {title}  ({len(hits)} hit(s))'])
                for prefix, line, content, needle in hits:
                    lines.extend([f'  {prefix}L{line}: {content}', f'          ^ {label}: "{needle}"'])
                lines.extend(['', '  ' + rule])
        lines.extend(['', 'Fix all of the above in one revision. A partial fix will block again.', '',
                      'BYPASS SENTINEL  <!-- discipline-bypass -->  IS A LAST RESORT.',
                      'Use it ONLY for a genuine false positive when no equivalent rephrasing preserves meaning.',
                      'Before adding it, state which hits it covers, why each is a false positive, and why no rephrasing is possible.',
                      'A real deferral is not a false positive and must use a durable sink.',
                      'The sentinel is a ONE-SHOT. After the bypassed action completes, REMOVE it in your next edit.',
                      'Response bypasses are ephemeral. Legacy <!-- mvp-meta --> and <!-- deferral-meta --> remain honored; use the canonical sentinel for new cases.', '',
                      'PERSISTENT ALLOWLIST -- for a RECURRING false positive, not a one-off.',
                      f'Add specific phrases to: {self.exceptions_file}',
                      "One phrase per line; '#' comments and blank lines are ignored. Include surrounding words (e.g. Tauri v2, not bare v2).",
                      'An entry must contain the flagged needle and occur in the flagged line; it cannot silence an unrelated violation on that line.',
                      'The allowlist is committed and code-reviewed. Do not use it to silence real violations.'])
        return '\n'.join(lines)


def last_assistant_text(transcript, tail_lines=200):
    if not transcript or not Path(transcript).is_file():
        return ''
    with Path(transcript).open(encoding='utf-8-sig', errors='replace') as stream:
        lines = deque(stream, maxlen=tail_lines)
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        message = record.get('message') or record
        if not isinstance(message, dict) or message.get('role') != 'assistant':
            continue
        content = message.get('content', [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return '\n'.join(item.get('text', '') for item in content
                             if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text', ''), str))
        return ''
    return ''
