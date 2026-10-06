"""Check the latest assistant response when a session stops."""
import os
import re

from codex_discipline_policy import DisciplinePolicy, WAITING, emit_json, has_bypass, last_assistant_text, read_input


def clarification_wait_matches(text):
    """Recognize waiting in a current question, not deferred task work.

    This permits stopping with a complete clarification checkpoint. It grants
    no authority to act on an answer and does not exempt other checkpoint text.
    """
    lines = text.splitlines()
    if not lines:
        return set()
    heading = re.fullmatch(r'BLOCKED ([A-Za-z0-9_./:-]+), revision (\S[^\n]*)\.', lines[0].strip())
    if not heading:
        return set()
    fields = {}
    for line in lines[1:]:
        label, separator, value = line.partition(':')
        if separator:
            fields.setdefault(label.strip(), []).append(value.strip())
    required = ('Question', 'Options', 'Recommendation', 'Evidence', 'Constraints',
                'Action withheld', 'Parent', 'Independent work', 'Descendants', 'Status')
    if any(len(fields.get(label, [])) != 1 or not fields[label][0] for label in required):
        return set()
    options = [option.strip().rstrip('.') for option in fields['Options'][0].split(';')]
    if len(options) not in (2, 3) or any(not option for option in options):
        return set()
    if fields['Recommendation'][0].rstrip('.') not in options:
        return set()
    question_id = re.escape(heading[1])
    question_reference = r'(?:' + question_id + r'|`' + question_id + r'`)'
    status = re.compile(r'(?:blocked on|awaiting|pending) the (?:parent|user) '
                        r'answer to ' + question_reference + r'\.')
    if not status.fullmatch(fields['Status'][0]):
        return set()
    question_fields = {'Question', 'Options', 'Recommendation', 'Evidence',
                       'Constraints', 'Action withheld', 'Status'}
    reference = re.compile(r'(?:the (?:parent|user) answer to ' + question_reference
                           + r'|this (?:question|decision|choice|target choice))(?=\s|$|\.(?:\s|$))')
    return {(index, match.start()) for index, line in enumerate(lines, 1)
            if line.partition(':')[0].strip() in question_fields
            for match in WAITING.finditer(line)
            if reference.match(line[match.end():].lstrip())}


def main():
    hook_input = read_input()
    try:
        tail_lines = max(1, int(os.environ.get('DISCIPLINE_TRANSCRIPT_TAIL_LINES', '200')))
    except ValueError:
        tail_lines = 200
    text = hook_input.get('last_assistant_message')
    if not isinstance(text, str) or not text:
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
    scan_text = '\n'.join(lines)
    mvp_hits, deferrals = policy.scan(scan_text, clarification_waits=clarification_wait_matches(scan_text))
    emit_json({'decision': 'block', 'reason': policy.report('response', 'your last response', mvp_hits, deferrals)
               + ' If already done, ignore silently and continue.'}
              if mvp_hits or deferrals else {'continue': True})


if __name__ == '__main__':
    main()
