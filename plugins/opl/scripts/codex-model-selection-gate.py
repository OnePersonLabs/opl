#!/usr/bin/env python3
"""Require deliberate model settings on recognizable direct Codex exec calls."""

import json
import re
import sys


VALUE_OPTIONS = {
    '-c', '--config', '-m', '--model', '-C', '--cd', '-p', '--profile',
    '-s', '--sandbox', '-i', '--image', '-o', '--output-last-message',
    '--thread-source', '--output-schema', '--base', '--commit', '--title',
    '--color', '--local-provider', '--enable', '--disable', '--add-dir',
}
SUBCOMMANDS = {'fork', 'resume', 'review'}


def skip_heredoc_bodies(command, start, delimiters):
    """Skip literal here-document lines after their command's newline."""
    for delimiter, strip_tabs in delimiters:
        while start < len(command):
            end = command.find('\n', start)
            if end < 0:
                end = len(command)
            line = command[start:end].rstrip('\r')
            if (line.lstrip('\t') if strip_tabs else line) == delimiter:
                start = min(end + 1, len(command))
                break
            start = min(end + 1, len(command))
    return start


def shell_tokens(command):
    """Tokenize literal shell words and command boundaries, not shell programs."""
    tokens = []
    word = []
    started = False
    quote = None
    heredocs = []
    index = 0
    while index < len(command):
        char = command[index]
        if not quote and char in ('`', '\\') and index + 1 < len(command) and command[index + 1] in '\r\n':
            index += 1
            if command[index] == '\r' and index + 1 < len(command) and command[index + 1] == '\n':
                index += 1
            index += 1
            continue
        if quote:
            if char == quote:
                quote = None
            elif char == '`' and index + 1 < len(command):
                index += 1
                word.append(command[index])
            else:
                word.append(char)
        elif char in ('"', "'"):
            quote = char
            started = True
        elif char == '#' and not started:
            end = command.find('\n', index)
            if end < 0:
                break
            index = end
            continue
        elif char.isspace():
            if started:
                tokens.append(''.join(word))
                word = []
                started = False
            if char in '\r\n':
                tokens.append(None)
                if char == '\n' and heredocs:
                    index = skip_heredoc_bodies(command, index + 1, heredocs)
                    heredocs = []
                    continue
        elif char in ';&|':
            if started:
                tokens.append(''.join(word))
                word = []
                started = False
            tokens.append(None)
        elif char == '<':
            marker = re.match(r'''<<(-?)[ \t]*(?:'([^']+)'|"([^"]+)"|\\([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))''', command[index:])
            if marker:
                heredocs.append((next(value for value in marker.groups()[1:] if value), bool(marker.group(1))))
            word.append(char)
            started = True
        elif char == '\\' and index + 1 < len(command) and command[index + 1] in ('"', "'"):
            index += 1
            word.append(command[index])
            started = True
        else:
            word.append(char)
            started = True
        index += 1
    if started:
        tokens.append(''.join(word))
    return tokens


def executable(token):
    name = re.split(r'[/\\]', token)[-1].lower()
    return name in {'codex', 'codex.exe', 'codex.cmd', 'codex.bat'}


def setting(option, value, found):
    if not value or not value.strip('"\' '):
        return
    if option in ('-m', '--model'):
        found.add('model')
    elif option in ('-c', '--config'):
        key, separator, config_value = value.partition('=')
        if separator and config_value.strip('"\' '):
            if key in ('model', 'model_reasoning_effort'):
                found.add(key)


def missing_settings(words):
    """Return missing settings for a direct codex exec, or None otherwise."""
    assignment_index = 0
    while assignment_index < len(words) and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', words[assignment_index]):
        assignment_index += 1
    words = words[assignment_index:]
    if words and re.split(r'[/\\]', words[0])[-1].lower() in {'env', 'env.exe'}:
        wrapper_index = 1
        while wrapper_index < len(words):
            word = words[wrapper_index]
            if word == '--' or word in ('-i', '--ignore-environment') or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', word):
                wrapper_index += 1
            elif word in ('-u', '--unset', '-C', '--chdir'):
                wrapper_index += 2
            elif word.startswith('-'):
                return None
            else:
                break
        words = words[wrapper_index:]
    if not words or not executable(words[0]):
        return None
    found = set()
    index = 1
    in_exec = False
    subcommand = None
    positional = 0
    while index < len(words):
        word = words[index]
        if word in ('exec', 'e') and not in_exec:
            in_exec = True
            index += 1
            continue
        if in_exec and subcommand is None and word in SUBCOMMANDS:
            subcommand = word
            index += 1
            continue
        if word in ('--', '-'):
            break
        option, equal, inline = word.partition('=')
        if equal and option in VALUE_OPTIONS:
            setting(option, inline, found)
            index += 1
            continue
        if word.startswith('-m') and word != '-m' and not word.startswith('--'):
            setting('-m', word[2:], found)
            index += 1
            continue
        if word.startswith('-c') and word != '-c' and not word.startswith('--'):
            setting('-c', word[2:], found)
            index += 1
            continue
        if word in VALUE_OPTIONS:
            value = words[index + 1] if index + 1 < len(words) else ''
            setting(word, value, found)
            index += 2
            continue
        if word.startswith('-'):
            index += 1
            continue
        if not in_exec:
            return None
        if subcommand in ('fork', 'resume') and positional == 0:
            positional += 1
            index += 1
            continue
        break  # The prompt is positional; its contents are not CLI settings.
    if not in_exec:
        return None
    return [name for name in ('model', 'model_reasoning_effort') if name not in found]


def first_missing(command):
    segment = []
    for token in shell_tokens(command) + [None]:
        if token is None:
            missing = missing_settings(segment)
            if missing:
                return missing
            segment = []
        else:
            segment.append(token)
    return None


def main():
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError('hook input must be a JSON object')
    tool_input = payload.get('tool_input', {})
    if not isinstance(tool_input, dict):
        raise ValueError('tool_input must be a JSON object')
    command = tool_input.get('command', tool_input.get('cmd', ''))
    if not isinstance(command, str):
        raise ValueError('tool_input.command must be a string')
    missing = first_missing(command)
    if not missing:
        print('{}')
        return
    labels = ', '.join(missing)
    reason = (
        f'codex exec needs an explicit {labels} for this child task. '
        'Retry with: codex exec -m gpt-6-sol -c model_reasoning_effort=medium '
        '"<task prompt>" (adjust both settings to the task).'
    )
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
    }}))


if __name__ == '__main__':
    try:
        main()
    except (TypeError, ValueError) as error:
        detail = f'invalid JSON hook input: {error}' if isinstance(error, json.JSONDecodeError) else str(error)
        print(f'codex-model-selection-gate: {detail}', file=sys.stderr)
        sys.exit(2)
