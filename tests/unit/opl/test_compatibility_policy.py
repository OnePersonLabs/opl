"""Public policy decisions over a fixed, credential-free Codex inventory."""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / 'plugins/opl/scripts/opl_compatibility_policy.py'
SPEC = importlib.util.spec_from_file_location('opl_compatibility_policy', MODULE)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def inventory(*items, complete=True):
    return {'items': list(items),
            'complete': {'plugin': complete, 'skill': complete, 'mcp': complete},
            'diagnostics': []}


def skill(name, identity, *, provider=None, enabled=True, path=None):
    value = {'kind': 'skill', 'name': name, 'id': identity,
             'plugin': provider, 'enabled': enabled}
    if path is not None:
        value['path'] = path
    return value


class PolicyTests(unittest.TestCase):
    def test_disabled_rule_owner_does_not_activate_conflicts(self):
        value = {'version': 1, 'rules': [{
            'id': 'opl.debug',
            'whenEnabled': {'kind': 'skill', 'name': 'debug', 'plugin': 'opl@market'},
            'disallowed': [{'kind': 'skill', 'name': 'debug'}],
        }]}
        result = policy.evaluate_policy(value, inventory(
            skill('debug', 'own', provider='opl@market', enabled=False),
            skill('debug', 'alternative', provider='other@market')))
        self.assertEqual(result, [])

    def test_active_rule_excludes_own_skill_and_reports_standalone_alternative(self):
        value = {'version': 1, 'rules': [{
            'id': 'opl.debug', 'reason': 'Use one debugging workflow.',
            'whenEnabled': {'kind': 'skill', 'name': 'debug', 'plugin': 'opl@market'},
            'disallowed': [{'kind': 'skill', 'name': 'debug'}],
        }]}
        result = policy.evaluate_policy(value, inventory(
            skill('debug', 'own', provider='opl@market'),
            skill('debug', 'standalone', path='/local/debug/SKILL.md')))
        self.assertEqual([item['code'] for item in result], ['disallowed_enabled'])
        self.assertEqual(result[0]['ruleId'], 'opl.debug')
        self.assertEqual(result[0]['reason'], 'Use one debugging workflow.')
        self.assertEqual([item['id'] for item in result[0]['matches']], ['standalone'])

    def test_provider_qualified_selectors_and_plugin_ids_are_exact(self):
        value = {'version': 1, 'required': [
            {'kind': 'skill', 'name': 'debug', 'plugin': 'opl@market'},
            {'kind': 'plugin', 'id': 'opl@market'},
            {'kind': 'mcp', 'name': 'docs', 'plugin': 'opl@market'},
        ]}
        result = policy.evaluate_policy(value, inventory(
            skill('debug', 'other', provider='other@market'),
            {'kind': 'plugin', 'id': 'opl@elsewhere', 'name': 'opl', 'enabled': True},
            {'kind': 'mcp', 'id': 'docs', 'name': 'docs', 'plugin': None, 'enabled': True}))
        self.assertEqual([item['code'] for item in result], ['required_missing'] * 3)
        self.assertEqual(result[0]['ruleId'], 'policy#/required/0')

    def test_nested_companions_require_each_enabled_ancestor(self):
        value = {'version': 1, 'recommended': [{
            'kind': 'skill', 'name': 'review', 'whenEnabled': {
                'required': [{'kind': 'skill', 'name': 'research', 'whenEnabled': {
                    'recommended': [{'kind': 'mcp', 'name': 'docs'}],
                }}],
            },
        }]}
        inactive = policy.evaluate_policy(value, inventory())
        self.assertEqual([item['code'] for item in inactive], ['recommended_missing'])
        partial = policy.evaluate_policy(value, inventory(skill('review', 'review')))
        self.assertEqual([item['code'] for item in partial], ['required_missing'])
        active = policy.evaluate_policy(value, inventory(skill('review', 'review'), skill('research', 'research')))
        self.assertEqual([item['code'] for item in active], ['recommended_missing'])
        self.assertEqual(active[0]['selector'], {'kind': 'mcp', 'name': 'docs'})
        self.assertEqual(active[0]['severity'], 'info')

    def test_enabled_presence_satisfies_even_an_incomplete_inventory(self):
        value = {'version': 1, 'required': [{'kind': 'skill', 'name': 'debug'}]}
        self.assertEqual(policy.evaluate_policy(value, inventory(skill('debug', 'active'), complete=False)), [])

    def test_disabled_unknown_and_incomplete_are_distinct(self):
        value = {'version': 1, 'required': [{'kind': 'skill', 'name': 'debug'}]}
        scenarios = [(False, True, 'required_missing'), (None, True, 'cannot_verify'),
                     (False, False, 'cannot_verify'), (None, False, 'cannot_verify')]
        for enabled, complete, expected in scenarios:
            with self.subTest(enabled=enabled, complete=complete):
                result = policy.evaluate_policy(value, inventory(skill('debug', 'debug', enabled=enabled), complete=complete))
                self.assertEqual([item['code'] for item in result], [expected])

    def test_unknown_forbidden_item_warns_and_enabled_match_still_fails(self):
        value = {'version': 1, 'disallowed': [{'kind': 'skill', 'name': 'debug'}]}
        result = policy.evaluate_policy(value, inventory(
            skill('debug', 'known'), skill('debug', 'uncertain', enabled=None)))
        self.assertEqual([item['code'] for item in result], ['disallowed_enabled', 'cannot_verify'])
        self.assertEqual([item['id'] for item in result[0]['matches']], ['known'])
        self.assertEqual([item['id'] for item in result[1]['matches']], ['uncertain'])

    def test_unknown_rule_owner_warns_without_claiming_downstream_violation(self):
        value = {'version': 1, 'rules': [{
            'id': 'conditional', 'whenEnabled': {'kind': 'skill', 'name': 'debug'},
            'required': [{'kind': 'mcp', 'name': 'docs'}],
        }]}
        result = policy.evaluate_policy(value, inventory(skill('debug', 'debug', enabled=None)))
        self.assertEqual([item['code'] for item in result], ['cannot_verify'])
        self.assertEqual(result[0]['selector'], {'kind': 'skill', 'name': 'debug'})

    def test_absolute_path_binds_own_rule_without_activating_other_copies(self):
        value = {'version': 1, 'rules': [{
            'id': 'own-copy', 'whenEnabled': {'kind': 'skill', 'name': 'debug', 'path': 'C:/Installed/opl/skills/debug/SKILL.md'},
            'disallowed': [{'kind': 'skill', 'name': 'debug'}],
        }]}
        self.assertEqual(policy.evaluate_policy(value, inventory(
            skill('debug', 'another-copy', path='C:/Other/opl/skills/debug/SKILL.md'))), [])
        result = policy.evaluate_policy(value, inventory(
            skill('debug', 'own', path='c:\\installed\\OPL\\skills\\debug\\skill.md'),
            skill('debug', 'other', path='C:/Other/debug/SKILL.md')))
        self.assertEqual([item['id'] for item in result[0]['matches']], ['other'])

    def test_matching_skill_with_unknown_path_cannot_establish_absence(self):
        value = {'version': 1, 'required': [{'kind': 'skill', 'name': 'debug', 'path': '/installed/debug/SKILL.md'}]}
        result = policy.evaluate_policy(value, inventory(skill('debug', 'unknown-path', enabled=None)))
        self.assertEqual([item['code'] for item in result], ['cannot_verify'])

    def test_active_required_and_forbidden_identity_reports_policy_conflict(self):
        value = {'version': 1,
                 'required': [{'kind': 'skill', 'name': 'debug', 'plugin': 'opl@market'}],
                 'disallowed': [{'kind': 'skill', 'name': 'debug'}]}
        result = policy.evaluate_policy(value, inventory(skill('debug', 'debug', provider='opl@market')))
        self.assertEqual([item['code'] for item in result], ['disallowed_enabled', 'policy_conflict'])
        self.assertEqual(result[-1]['severity'], 'error')

    def test_contradiction_is_visible_when_identity_is_missing(self):
        selector = {'kind': 'plugin', 'id': 'opl@market'}
        result = policy.evaluate_policy({'version': 1, 'required': [selector], 'disallowed': [selector]}, inventory())
        self.assertEqual([item['code'] for item in result], ['required_missing', 'policy_conflict'])

    def test_narrow_forbid_does_not_contradict_broad_requirement_with_an_allowed_match(self):
        value = {'version': 1, 'required': [{'kind': 'skill', 'name': 'debug'}],
                 'disallowed': [{'kind': 'skill', 'name': 'debug', 'plugin': 'other@market'}]}
        result = policy.evaluate_policy(value, inventory(
            skill('debug', 'own', provider='opl@market'), skill('debug', 'other', provider='other@market')))
        self.assertEqual([item['code'] for item in result], ['disallowed_enabled'])

    def test_mutual_requirements_evaluate_inventory_without_dependency_recursion(self):
        value = {'version': 1, 'rules': [
            {'id': 'a', 'whenEnabled': {'kind': 'skill', 'name': 'a'},
             'required': [{'kind': 'skill', 'name': 'b'}]},
            {'id': 'b', 'whenEnabled': {'kind': 'skill', 'name': 'b'},
             'required': [{'kind': 'skill', 'name': 'a'}]},
        ]}
        self.assertEqual(policy.evaluate_policy(value, inventory(skill('a', 'a'), skill('b', 'b'))), [])

    def test_ignored_rule_requires_exact_known_id_and_reason(self):
        value = {'version': 1, 'rules': [{'id': 'built-in',
                 'whenEnabled': {'kind': 'skill', 'name': 'debug'},
                 'required': [{'kind': 'mcp', 'name': 'docs'}]}],
                 'ignoreRules': [{'id': 'built-in', 'reason': 'This project uses offline docs.'}]}
        self.assertEqual(policy.evaluate_policy(value, inventory(skill('debug', 'debug'))), [])
        value['ignoreRules'][0]['id'] = 'typo'
        with self.assertRaisesRegex(policy.PolicyError, r'project#/ignoreRules/0/id: unknown rule ID'):
            policy.evaluate_policy(value, inventory(), source='project')

    def test_normalization_is_independent_and_has_explicit_defaults(self):
        value = {'version': 1, 'required': [{'kind': 'skill', 'name': 'debug', 'whenEnabled': {}}]}
        result = policy.validate_policy(value)
        self.assertEqual(result['onViolation'], 'acknowledge')
        self.assertEqual(result['rules'], [])
        self.assertEqual(result['ignoreRules'], [])
        self.assertEqual(result['required'][0]['whenEnabled'], {'required': [], 'recommended': [], 'disallowed': []})
        result['required'][0]['name'] = 'changed'
        self.assertEqual(value['required'][0]['name'], 'debug')

    def test_invalid_policy_errors_identify_source_and_pointer(self):
        scenarios = [
            ({'version': True}, '/version'),
            ({'version': 1, 'unknown': []}, '/unknown'),
            ({'version': 1, 'required': [{'kind': 'plugin', 'name': 'opl'}]}, '/required/0/name'),
            ({'version': 1, 'required': [{'kind': 'plugin', 'id': 'opl'}]}, '/required/0/id'),
            ({'version': 1, 'required': [{'kind': 'mcp', 'name': 'docs', 'path': '/docs'}]}, '/required/0/path'),
            ({'version': 1, 'required': [{'kind': 'skill', 'name': 'debug', 'path': '../debug'}]}, '/required/0/path'),
            ({'version': 1, 'disallowed': [{'kind': 'skill', 'name': 'debug', 'whenEnabled': {}}]}, '/disallowed/0/whenEnabled'),
            ({'version': 1, 'ignoreRules': [{'id': 'x', 'reason': '  '}]}, '/ignoreRules/0/reason'),
            ({'version': 1, 'required': [{'kind': 'skill', 'name': 'debug', 'command': 'anything'}]}, '/required/0/command'),
            ({'version': 1, 'required': set()}, '/required'),
        ]
        for value, pointer in scenarios:
            with self.subTest(pointer=pointer), self.assertRaises(policy.PolicyError) as raised:
                policy.validate_policy(value, source='project')
            self.assertTrue(str(raised.exception).startswith('project#' + pointer + ':'), str(raised.exception))

    def test_large_and_cyclic_policies_fail_with_actionable_limits(self):
        with self.assertRaisesRegex(policy.PolicyError, '1000'):
            policy.validate_policy({'version': 1, 'required': [{'kind': 'skill', 'name': 'debug'}] * 1001})
        with self.assertRaisesRegex(policy.PolicyError, '4096'):
            policy.validate_policy({'version': 1, '$schema': 'x' * 4097})
        value = {'version': 1}
        value['required'] = [value]
        with self.assertRaisesRegex(policy.PolicyError, 'cyclic'):
            policy.validate_policy(value)
        value = {'version': 1}
        block = value
        for _ in range(9):
            block['required'] = [{'kind': 'skill', 'name': 'debug', 'whenEnabled': {}}]
            block = block['required'][0]['whenEnabled']
        with self.assertRaisesRegex(policy.PolicyError, 'nesting exceeds 8'):
            policy.validate_policy(value)

    def test_matches_do_not_leak_inventory_transport_or_credentials(self):
        item = skill('debug', 'debug')
        item['transport'] = {'env': {'TOKEN': 'secret'}}
        result = policy.evaluate_policy({'version': 1, 'disallowed': [{'kind': 'skill', 'name': 'debug'}]}, inventory(item))
        self.assertNotIn('transport', result[0]['matches'][0])

    def test_discovery_defers_rule_companions_until_owner_is_definitely_enabled(self):
        owner = {'kind': 'skill', 'name': 'research', 'plugin': 'opl@market'}
        docs = {'kind': 'mcp', 'name': 'docs'}
        value = {'version': 1, 'rules': [{'id': 'research-docs', 'whenEnabled': owner,
                                        'required': [docs]}]}
        for enabled in (False, None):
            with self.subTest(enabled=enabled):
                current = inventory(skill('research', 'own', provider='opl@market', enabled=enabled), complete=False)
                self.assertEqual(policy.active_selectors(value, current), [owner])
        self.assertEqual(policy.active_selectors(value, inventory()), [owner])
        current = inventory(skill('research', 'own', provider='opl@market'), complete=False)
        self.assertEqual(policy.active_selectors(value, current), [owner, docs])

    def test_discovery_preserves_every_nested_positive_activation_condition(self):
        value = {'version': 1, 'required': [{
            'kind': 'skill', 'name': 'review', 'whenEnabled': {
                'recommended': [{'kind': 'skill', 'name': 'research', 'whenEnabled': {
                    'disallowed': [{'kind': 'mcp', 'name': 'remote-docs'}],
                }}],
            },
        }], 'recommended': [{'kind': 'plugin', 'id': 'tools@market'}],
            'disallowed': [{'kind': 'skill', 'name': 'legacy'}]}
        initial = [{'kind': 'skill', 'name': 'review'}, {'kind': 'plugin', 'id': 'tools@market'},
                   {'kind': 'skill', 'name': 'legacy'}]
        self.assertEqual(policy.active_selectors(value, inventory(skill('research', 'research'))), initial)
        partial = policy.active_selectors(value, inventory(skill('review', 'review')))
        self.assertEqual(partial, [initial[0], {'kind': 'skill', 'name': 'research'}, *initial[1:]])
        active = policy.active_selectors(value, inventory(skill('review', 'review'), skill('research', 'research')))
        self.assertEqual(active, [initial[0], {'kind': 'skill', 'name': 'research'},
                                  {'kind': 'mcp', 'name': 'remote-docs'}, *initial[1:]])

    def test_discovery_omits_ignored_rules_and_rejects_unknown_ignore_ids(self):
        value = {'version': 1, 'rules': [{'id': 'ignored',
                 'whenEnabled': {'kind': 'skill', 'name': 'research'},
                 'required': [{'kind': 'mcp', 'name': 'docs'}]}],
                 'ignoreRules': [{'id': 'ignored', 'reason': 'Offline project.'}]}
        self.assertEqual(policy.active_selectors(value, inventory(skill('research', 'research'))), [])
        value['ignoreRules'][0]['id'] = 'misspelled'
        with self.assertRaisesRegex(policy.PolicyError, r'policy#/ignoreRules/0/id: unknown rule ID'):
            policy.active_selectors(value, inventory())

    def test_discovery_uses_exact_own_path_binding_and_deduplicates_selectors(self):
        owner = {'kind': 'skill', 'name': 'research', 'path': 'C:/Installed/research/SKILL.md'}
        docs = {'kind': 'mcp', 'name': 'docs', 'plugin': 'docs@market'}
        value = {'version': 1, 'rules': [{'id': 'own', 'whenEnabled': owner,
                                        'required': [docs], 'recommended': [docs]}]}
        for candidate in (skill('research', 'unknown-path'),
                          skill('research', 'other-path', path='C:/Other/research/SKILL.md')):
            with self.subTest(identity=candidate['id']):
                self.assertEqual(policy.active_selectors(value, inventory(candidate)), [owner])
        active = skill('research', 'own', path='c:\\installed\\RESEARCH\\skill.md')
        self.assertEqual(policy.active_selectors(value, inventory(active)), [owner, docs])


if __name__ == '__main__':
    unittest.main()
