"""Validate declarative compatibility policies and evaluate a fixed inventory.

This module performs no discovery, execution, installation, or activation. An
incomplete inventory can establish presence but cannot establish absence.
"""

from pathlib import PurePosixPath, PureWindowsPath
import math
import re


MAX_ENTRIES = 1000
MAX_NESTING = 8
MAX_STRING = 4096
KINDS = ('plugin', 'skill', 'mcp')
CATEGORIES = ('required', 'recommended', 'disallowed')
SELECTOR_FIELDS = ('kind', 'id', 'name', 'plugin', 'path')
PLUGIN_ID = re.compile(r'^[^@\s/\\]+@[^@\s/\\]+$')


class PolicyError(ValueError):
    """A policy is invalid; the message identifies its source and JSON pointer."""


def _pointer(path, key):
    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')


class _Validator:
    def __init__(self, source):
        self.source = source
        self.entries = 0
        self.nodes = 0

    def error(self, path, message):
        raise PolicyError(f'{self.source}#{path}: {message}')

    def json(self, value, path='', ancestors=None, depth=0):
        ancestors = set() if ancestors is None else ancestors
        self.nodes += 1
        if self.nodes > 20000:
            self.error(path, 'policy exceeds 20000 JSON values')
        if depth > 40:
            self.error(path, 'JSON nesting exceeds 40 levels')
        if value is None or type(value) in (bool, int):
            return
        if type(value) is str:
            if len(value) > MAX_STRING:
                self.error(path, f'string exceeds {MAX_STRING} characters')
            return
        if type(value) is float and math.isfinite(value):
            return
        if type(value) not in (dict, list):
            self.error(path, 'expected a JSON value')
        if id(value) in ancestors:
            self.error(path, 'cyclic values are not JSON')
        ancestors.add(id(value))
        values = value.items() if type(value) is dict else enumerate(value)
        for key, child in values:
            if type(value) is dict and type(key) is not str:
                self.error(path, 'JSON object keys must be strings')
            self.json(child, _pointer(path, key), ancestors, depth + 1)
        ancestors.remove(id(value))

    def obj(self, value, allowed, path):
        if type(value) is not dict:
            self.error(path, 'expected an object')
        for key in value:
            if key not in allowed:
                self.error(_pointer(path, key), 'unknown property')

    def string(self, value, path):
        if type(value) is not str or not value.strip():
            self.error(path, 'expected a nonblank string')
        return value

    def array(self, value, path):
        if type(value) is not list:
            self.error(path, 'expected an array')
        if len(value) > MAX_ENTRIES:
            self.error(path, f'array exceeds {MAX_ENTRIES} entries')
        return value

    def count(self, path):
        self.entries += 1
        if self.entries > MAX_ENTRIES:
            self.error(path, f'policy exceeds {MAX_ENTRIES} declarations')

    def selector(self, value, path, *, entry=False, nested=False, depth=0):
        self.count(path)
        allowed = set(SELECTOR_FIELDS)
        if entry:
            allowed.add('reason')
        if nested:
            allowed.add('whenEnabled')
        self.obj(value, allowed, path)
        kind = value.get('kind')
        if kind not in KINDS:
            self.error(_pointer(path, 'kind'), 'expected plugin, skill, or mcp')
        permitted = {'kind', 'id'} if kind == 'plugin' else {'kind', 'name', 'plugin'}
        if kind == 'skill':
            permitted.add('path')
        for key in SELECTOR_FIELDS:
            if key in value and key not in permitted:
                self.error(_pointer(path, key), f'{key} is not valid for {kind} selectors')
        identity = 'id' if kind == 'plugin' else 'name'
        self.string(value.get(identity), _pointer(path, identity))
        for key in ('id', 'plugin'):
            if key in value and not PLUGIN_ID.fullmatch(self.string(value[key], _pointer(path, key))):
                self.error(_pointer(path, key), 'expected a canonical name@marketplace plugin ID')
        result = {key: value[key] for key in SELECTOR_FIELDS if key in value}
        if 'path' in value:
            candidate = self.string(value['path'], _pointer(path, 'path'))
            if not (PurePosixPath(candidate).is_absolute() or PureWindowsPath(candidate).is_absolute()):
                self.error(_pointer(path, 'path'), 'expected an absolute skill path')
        if 'reason' in value:
            result['reason'] = self.string(value['reason'], _pointer(path, 'reason'))
        if 'whenEnabled' in value:
            if depth >= MAX_NESTING:
                self.error(_pointer(path, 'whenEnabled'), f'conditional nesting exceeds {MAX_NESTING} levels')
            result['whenEnabled'] = self.block(value['whenEnabled'], _pointer(path, 'whenEnabled'), depth + 1)
        return result

    def block(self, value, path, depth=0):
        self.obj(value, set(CATEGORIES), path)
        result = {}
        for category in CATEGORIES:
            entries_path = _pointer(path, category)
            entries = self.array(value.get(category, []), entries_path)
            result[category] = [self.selector(entry, _pointer(entries_path, i), entry=True,
                                              nested=category != 'disallowed', depth=depth)
                                for i, entry in enumerate(entries)]
        return result


def validate_policy(value: object, source: str = 'policy') -> dict:
    """Return a normalized policy or raise PolicyError with a source location."""
    validator = _Validator(source)
    validator.json(value)
    validator.obj(value, {'version', '$schema', 'onViolation', 'rules', 'ignoreRules', *CATEGORIES}, '')
    if type(value.get('version')) is not int or value['version'] != 1:
        validator.error('/version', 'expected policy version 1')
    action = value.get('onViolation', 'acknowledge')
    if action not in ('warn', 'acknowledge'):
        validator.error('/onViolation', 'expected warn or acknowledge')
    result = {'version': 1, 'onViolation': action}
    if '$schema' in value:
        result['$schema'] = validator.string(value['$schema'], '/$schema')
    result.update(validator.block({key: value[key] for key in CATEGORIES if key in value}, ''))
    result['rules'] = []
    rule_ids = set()
    for i, rule in enumerate(validator.array(value.get('rules', []), '/rules')):
        path = f'/rules/{i}'
        validator.obj(rule, {'id', 'whenEnabled', 'reason', *CATEGORIES}, path)
        rule_id = validator.string(rule.get('id'), path + '/id')
        if rule_id in rule_ids:
            validator.error(path + '/id', f'duplicate rule ID {rule_id!r}')
        rule_ids.add(rule_id)
        parsed = {'id': rule_id, 'whenEnabled': validator.selector(rule.get('whenEnabled'), path + '/whenEnabled')}
        if 'reason' in rule:
            parsed['reason'] = validator.string(rule['reason'], path + '/reason')
        parsed.update(validator.block({key: rule[key] for key in CATEGORIES if key in rule}, path))
        result['rules'].append(parsed)
    result['ignoreRules'] = []
    ignored_ids = set()
    for i, ignored in enumerate(validator.array(value.get('ignoreRules', []), '/ignoreRules')):
        path = f'/ignoreRules/{i}'
        validator.count(path)
        validator.obj(ignored, {'id', 'reason'}, path)
        rule_id = validator.string(ignored.get('id'), path + '/id')
        reason = validator.string(ignored.get('reason'), path + '/reason')
        if rule_id in ignored_ids:
            validator.error(path + '/id', f'duplicate ignored rule ID {rule_id!r}')
        ignored_ids.add(rule_id)
        result['ignoreRules'].append({'id': rule_id, 'reason': reason})
    return result


def _path_key(value):
    path = PureWindowsPath(value)
    return str(path).casefold() if path.is_absolute() else str(PurePosixPath(value))


def _selector(entry):
    return {key: entry[key] for key in SELECTOR_FIELDS if key in entry}


def _matches(selector, item):
    if item.get('kind') != selector['kind']:
        return False
    for key in ('id', 'name', 'plugin'):
        if key in selector and item.get(key) != selector[key]:
            return False
    if 'path' in selector:
        if not isinstance(item.get('path'), str):
            return None
        return _path_key(item['path']) == _path_key(selector['path'])
    return True


def _covers(forbidden, required):
    """Whether every identity selected by required is selected by forbidden."""
    for key, value in forbidden.items():
        if key not in required:
            return False
        if key == 'path':
            if _path_key(value) != _path_key(required[key]):
                return False
        elif value != required[key]:
            return False
    return True


def _safe_item(item):
    return {key: item[key] for key in ('kind', 'id', 'name', 'enabled', 'plugin', 'qualifiedName', 'path')
            if key in item and (item[key] is None or type(item[key]) in (str, bool))}


def _label(selector):
    label = f"{selector['kind']} {selector.get('id', selector.get('name'))!r}"
    if 'plugin' in selector:
        label += f" from {selector['plugin']!r}"
    if 'path' in selector:
        label += f" at {selector['path']!r}"
    return label


def _ignored_rule_ids(policy, source):
    known_ids = {rule['id'] for rule in policy['rules']}
    for i, entry in enumerate(policy['ignoreRules']):
        if entry['id'] not in known_ids:
            raise PolicyError(f"{source}#/ignoreRules/{i}/id: unknown rule ID {entry['id']!r}")
    return {entry['id'] for entry in policy['ignoreRules']}


def active_selectors(policy: dict, inventory: dict, source: str = 'policy') -> list[dict]:
    """Return selectors needed to discover currently reachable policy branches.

    Root entries and nonignored rule owners are always needed. A conditional
    body is reachable only when its owner definitely matches an enabled item;
    missing, disabled, and unknown owners do not activate discovery downstream.
    The result preserves first-seen order and contains each selector once.
    """
    policy = validate_policy(policy, source)
    ignored = _ignored_rule_ids(policy, source)
    items = inventory.get('items', [])
    result = []
    seen = set()

    def append(entry):
        selector = _selector(entry)
        identity = tuple((key, _path_key(value) if key == 'path' else value)
                         for key, value in selector.items())
        if identity not in seen:
            seen.add(identity)
            result.append(selector)
        return selector

    def enabled(selector):
        return any(item.get('enabled') is True and _matches(selector, item) is True for item in items)

    def block(value):
        for category in CATEGORIES:
            for entry in value[category]:
                selector = append(entry)
                if category != 'disallowed' and 'whenEnabled' in entry and enabled(selector):
                    block(entry['whenEnabled'])

    block(policy)
    for rule in policy['rules']:
        if rule['id'] in ignored:
            continue
        selector = append(rule['whenEnabled'])
        if enabled(selector):
            block(rule)
    return result


def evaluate_policy(policy: dict, inventory: dict, source: str = 'policy') -> list[dict]:
    """Evaluate active constraints without inferring missing or unknown state."""
    policy = validate_policy(policy, source)
    ignored = _ignored_rule_ids(policy, source)
    items = inventory.get('items', [])
    complete = inventory.get('complete', {})
    findings = []
    active_required = []
    active_disallowed = []

    def add(code, severity, selector, path, matches, rule_id=None, reason=None):
        messages = {
            'required_missing': 'Required {item} is not enabled.',
            'recommended_missing': 'Recommended {item} is not enabled.',
            'disallowed_enabled': 'Disallowed {item} is enabled.',
            'cannot_verify': 'Cannot verify {item}: inventory is incomplete or its enabled state is unknown.',
            'policy_conflict': 'Active policy requirements and prohibitions conflict for {item}.',
        }
        finding = {'code': code, 'severity': severity, 'ruleId': rule_id or f'{source}#{path}',
                   'message': messages[code].format(item=_label(selector)), 'source': source,
                   'selector': _selector(selector), 'matches': [_safe_item(item) for item in matches]}
        if reason is not None:
            finding['reason'] = reason
        findings.append(finding)

    def selected(selector, excluded=frozenset()):
        return [item for item in items if item.get('id') not in excluded and _matches(selector, item) is not False]

    def states(selector, matches):
        enabled = [item for item in matches if item.get('enabled') is True and _matches(selector, item) is True]
        unknown = [item for item in matches if item.get('enabled') is None
                   or (item.get('enabled') is not False and _matches(selector, item) is None)]
        return enabled, unknown

    def block(value, path, rule_id=None, reason=None, excluded=frozenset()):
        for category in CATEGORIES:
            for i, entry in enumerate(value[category]):
                entry_path = f'{path}/{category}/{i}'
                selector = _selector(entry)
                entry_reason = entry.get('reason', reason)
                matches = selected(selector, excluded if category == 'disallowed' else frozenset())
                enabled, unknown = states(selector, matches)
                if category in ('required', 'disallowed'):
                    constraint = {'selector': selector, 'path': entry_path, 'ruleId': rule_id,
                                  'reason': entry_reason, 'enabled': enabled, 'unknown': unknown,
                                  'excluded': excluded if category == 'disallowed' else frozenset()}
                    (active_required if category == 'required' else active_disallowed).append(constraint)
                if category == 'disallowed':
                    if enabled:
                        add('disallowed_enabled', 'error', selector, entry_path, enabled, rule_id, entry_reason)
                    if unknown or not complete.get(selector['kind'], False):
                        add('cannot_verify', 'warning', selector, entry_path, unknown, rule_id, entry_reason)
                elif not enabled:
                    if unknown or not complete.get(selector['kind'], False):
                        add('cannot_verify', 'warning', selector, entry_path, unknown, rule_id, entry_reason)
                    else:
                        add(category + '_missing', 'error' if category == 'required' else 'info',
                            selector, entry_path, matches, rule_id, entry_reason)
                if 'whenEnabled' in entry and enabled:
                    block(entry['whenEnabled'], entry_path + '/whenEnabled', rule_id, entry_reason,
                          excluded | {item['id'] for item in enabled})

    block(policy, '')
    for i, rule in enumerate(policy['rules']):
        if rule['id'] in ignored:
            continue
        selector = rule['whenEnabled']
        matches = selected(selector)
        enabled, unknown = states(selector, matches)
        if enabled:
            block(rule, f'/rules/{i}', rule['id'], rule.get('reason'), {item['id'] for item in enabled})
        elif unknown or not complete.get(selector['kind'], False):
            add('cannot_verify', 'warning', selector, f'/rules/{i}/whenEnabled', matches,
                rule['id'], rule.get('reason'))
    for required in active_required:
        selector = required['selector']
        enabled_ids = {item['id'] for item in required['enabled']}
        prohibited_ids = set()
        covering = []
        overlapping = []
        for forbidden in active_disallowed:
            forbidden_ids = {item['id'] for item in forbidden['enabled']}
            prohibited_ids.update(forbidden_ids)
            if enabled_ids & forbidden_ids:
                overlapping.append(forbidden)
            if _covers(forbidden['selector'], selector) and not enabled_ids & forbidden['excluded']:
                covering.append(forbidden)
        # A permitted enabled identity satisfies an existential requirement,
        # even if another identity with the same unqualified name is forbidden.
        if enabled_ids - prohibited_ids:
            continue
        exhausted = (enabled_ids and not required['unknown'] and complete.get(selector['kind'], False))
        if covering or exhausted:
            add('policy_conflict', 'error', selector, required['path'], required['enabled'],
                required['ruleId'], required['reason'])
            conflicts = covering or overlapping
            findings[-1]['relatedRuleIds'] = list(dict.fromkeys(
                constraint['ruleId'] or f"{source}#{constraint['path']}" for constraint in conflicts))
    return findings
