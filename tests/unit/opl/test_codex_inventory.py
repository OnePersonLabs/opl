"""Exercise the inventory adapter against a real, isolated stdio CLI process."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / 'plugins/opl/scripts/opl_codex_inventory.py'
FAKE_CODEX = ROOT / 'tests/fixtures/opl-compatibility/inventory/codex.py'


class InventoryTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('opl_codex_inventory', MODULE)
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / 'project with spaces'
        self.cwd.mkdir()
        self.home = self.root / 'codex home'
        self.home.mkdir()
        self.fixture = self.root / 'responses.json'
        self.calls = self.root / 'calls.jsonl'
        self.data = {
            'plugins': {'installed': [
                {'pluginId': 'alpha@market', 'name': 'alpha', 'installed': True,
                 'enabled': True, 'source': {'path': '/authoring/not-installed'}},
                {'pluginId': 'beta@market', 'name': 'beta', 'installed': True, 'enabled': False},
            ], 'available': []},
            'mcps': [{'name': 'shared', 'enabled': False, 'disabled_reason': 'disabled',
                      'transport': {'env': {'SECRET': 'NEVER_PRINT_THIS'}}}],
            'skills': {'data': [{'cwd': str(self.cwd), 'skills': [
                {'name': 'alpha:debug', 'pluginId': 'alpha@market',
                 'path': '/installed/alpha/skills/debug/SKILL.md', 'enabled': True},
                {'name': 'debug', 'pluginId': None, 'path': '/project/debug/SKILL.md', 'enabled': False},
            ], 'errors': []}]},
            'config': {'config': {'mcp_servers': {'shared': {'enabled': False}}}, 'layers': []},
        }
        self.environment = patch.dict(os.environ, {
            'CODEX_BIN': str(FAKE_CODEX), 'INVENTORY_FIXTURE': str(self.fixture),
            'INVENTORY_CALLS': str(self.calls), 'INVENTORY_CWD': str(self.cwd),
            'INVENTORY_HOME': str(self.home),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def collect(self, **kwargs):
        self.fixture.write_text(json.dumps(self.data), encoding='utf-8')
        return self.adapter.collect_inventory(self.cwd, codex_home=self.home, **kwargs)

    def test_collects_native_inventory_without_exposing_transports_or_source_roots(self):
        result = self.collect()
        self.assertEqual(result['complete'], {'plugin': True, 'skill': True, 'mcp': True})
        plugins = [item for item in result['items'] if item['kind'] == 'plugin']
        self.assertEqual([(item['id'], item['enabled']) for item in plugins],
                         [('alpha@market', True), ('beta@market', False)])
        self.assertNotIn('path', plugins[0])
        skills = [item for item in result['items'] if item['kind'] == 'skill']
        self.assertEqual([(item['name'], item['plugin'], item['enabled']) for item in skills],
                         [('debug', 'alpha@market', True), ('debug', None, False)])
        self.assertNotEqual(skills[0]['id'], skills[1]['id'])
        mcps = [item for item in result['items'] if item['kind'] == 'mcp']
        self.assertEqual([(item['name'], item['enabled'], item['plugin']) for item in mcps],
                         [('shared', False, None)])
        self.assertNotIn('NEVER_PRINT_THIS', json.dumps(result))
        self.assertNotIn('transport', json.dumps(result))
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertTrue(all(call['cwd'] == str(self.cwd) and call['home'] == str(self.home) for call in calls))
        self.assertIn('skills/list', [call.get('method') for call in calls])

    def test_attributes_plugin_mcps_and_preserves_user_shadowing_and_disabled_plugins(self):
        self.data['mcps'].append({'name': 'cloud', 'enabled': True})
        self.data['details'] = {'alpha@market': ['cloud', 'shared'], 'beta@market': ['paused']}
        result = self.collect()
        mcps = {(item['name'], item['plugin']): item for item in result['items'] if item['kind'] == 'mcp'}
        self.assertIn(('cloud', 'alpha@market'), mcps)
        self.assertEqual(mcps[('cloud', 'alpha@market')]['enabled'], True)
        self.assertEqual(mcps[('shared', None)]['enabled'], False)
        self.assertEqual(mcps[('shared', 'alpha@market')]['enabled'], False)
        self.assertIn('shadow', mcps[('shared', 'alpha@market')]['reason'])
        self.assertEqual(mcps[('paused', 'beta@market')]['enabled'], False)
        self.assertTrue(result['complete']['mcp'])

    def test_plugin_name_collisions_are_unknown_without_erasing_name_only_inventory(self):
        self.data['plugins']['installed'][1]['enabled'] = True
        self.data['mcps'] = [{'name': 'cloud', 'enabled': True}]
        self.data['details'] = {'alpha@market': ['cloud'], 'beta@market': ['cloud']}
        result = self.collect()
        mcps = {(item['name'], item['plugin']): item for item in result['items'] if item['kind'] == 'mcp'}
        self.assertTrue(mcps[('cloud', None)]['enabled'])
        self.assertIn(('cloud', 'alpha@market'), mcps)
        self.assertIsNone(mcps[('cloud', 'alpha@market')]['enabled'])
        self.assertIsNone(mcps[('cloud', 'beta@market')]['enabled'])
        self.assertFalse(result['complete']['mcp'])
        self.assertIn('codex_mcp_owner_ambiguous', [entry['code'] for entry in result['diagnostics']])

    def test_skill_only_inventory_does_not_query_plugin_or_mcp_catalogs(self):
        self.data['config']['layers'] = [
            {'name': {'type': 'user', 'file': '/native/config.toml'}},
            {'name': {'type': 'project', 'dotCodexFolder': '/project/.codex'}},
        ]
        result = self.collect(kinds={'skill'})
        self.assertEqual(result['complete'], {'plugin': False, 'skill': True, 'mcp': False})
        self.assertTrue(all(item['kind'] == 'skill' for item in result['items']))
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual([call['args'] for call in calls if 'args' in call],
                         [['app-server', '--listen', 'stdio://']])
        self.assertEqual([call['method'] for call in calls if 'method' in call],
                         ['initialize', 'initialized', 'skills/list', 'config/read'])
        self.assertIn('/native/config.toml', result['watchPaths'])
        self.assertIn(str(Path('/project/.codex') / 'config.toml'), result['watchPaths'])

    def test_empty_requested_inventory_does_not_launch_codex(self):
        result = self.collect(kinds=set())
        self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostics'], [])
        self.assertFalse(self.calls.exists())

    def test_partial_plugin_read_failure_keeps_other_inventory_and_names_the_provider(self):
        self.data['details'] = {'alpha@market': ['cloud']}
        self.data['mcps'].append({'name': 'cloud', 'enabled': True})
        self.data['rpcErrors'] = {'plugin/read:beta': {'code': -32600, 'message': 'NEVER_PRINT_THIS'}}
        result = self.collect()
        self.assertFalse(result['complete']['mcp'])
        self.assertTrue(result['complete']['skill'])
        diagnostics = [item for item in result['diagnostics'] if item.get('operation') == 'plugin/read']
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].get('plugin'), 'beta@market')
        self.assertNotIn('NEVER_PRINT_THIS', json.dumps(result))
        cloud = next(item for item in result['items'] if item['kind'] == 'mcp' and item['plugin'] == 'alpha@market')
        self.assertIsNone(cloud['enabled'])

    def test_malformed_skill_entry_preserves_known_skills_and_prevents_absence_inference(self):
        self.data['skills']['data'][0]['skills'].append({'enabled': True})
        result = self.collect(kinds={'skill'})
        self.assertFalse(result['complete']['skill'])
        self.assertEqual(len(result['items']), 2)
        self.assertIn('codex_invalid_response', [item['code'] for item in result['diagnostics']])

    def test_omitted_skill_provenance_is_unknown_and_preserves_other_valid_skills(self):
        del self.data['skills']['data'][0]['skills'][0]['pluginId']
        result = self.collect(kinds={'skill'})
        self.assertFalse(result['complete']['skill'])
        self.assertIn('codex_skill_provenance_unavailable', [item['code'] for item in result['diagnostics']])
        self.assertEqual([(item['name'], item['plugin'], item['enabled']) for item in result['items']],
                         [('debug', None, False)])

    def test_skill_load_errors_are_not_an_empty_success(self):
        self.data['skills']['data'][0]['errors'] = [{'message': 'NEVER_PRINT_THIS'}]
        result = self.collect(kinds={'skill'})
        self.assertFalse(result['complete']['skill'])
        self.assertIn('codex_skill_load_errors', [item['code'] for item in result['diagnostics']])
        self.assertNotIn('NEVER_PRINT_THIS', json.dumps(result))

    def test_timeout_is_bounded_and_retry_is_visible(self):
        self.data['hang'] = 'skills/list'
        started = time.monotonic()
        result = self.collect(kinds={'skill'}, timeout=1.5)
        self.assertLess(time.monotonic() - started, 4)
        self.assertFalse(result['complete']['skill'])
        codes = [item['code'] for item in result['diagnostics']]
        self.assertIn('codex_query_retry', codes)
        self.assertIn('codex_query_timeout', codes)

    def test_null_metadata_response_is_a_diagnosed_protocol_failure(self):
        self.data['plugins'] = None
        result = self.collect(kinds={'plugin'})
        self.assertFalse(result['complete']['plugin'])
        self.assertIn('codex_invalid_response', [item['code'] for item in result['diagnostics']])

    def test_missing_codex_is_a_diagnosed_unknown(self):
        with patch.dict(os.environ, {'CODEX_BIN': str(self.root / 'missing-codex.exe')}):
            result = self.collect(kinds={'skill'})
        self.assertEqual(result['items'], [])
        self.assertFalse(result['complete']['skill'])
        self.assertIn('codex_launch_failed', [item['code'] for item in result['diagnostics']])

    def test_name_only_mcps_do_not_read_plugin_membership(self):
        result = self.collect(kinds={'mcp'}, mcp_plugins=set())
        self.assertTrue(result['complete']['mcp'])
        self.assertEqual([(item['name'], item['plugin']) for item in result['items']], [('shared', None)])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertNotIn('plugin/installed', [call.get('method') for call in calls])
        self.assertNotIn('plugin/read', [call.get('method') for call in calls])

    def test_metadata_batch_correlates_out_of_order_responses(self):
        self.data['reversePluginReads'] = True
        self.data['details'] = {'alpha@market': ['cloud'], 'beta@market': ['paused']}
        self.data['mcps'] = [{'name': 'cloud', 'enabled': True}]
        result = self.collect(kinds={'mcp'}, timeout=2)
        owners = {(item['name'], item['plugin']): item['enabled'] for item in result['items']}
        self.assertEqual(owners.get(('cloud', 'alpha@market')), True)
        self.assertEqual(owners.get(('paused', 'beta@market')), False)
        self.assertTrue(result['complete']['mcp'])

    def test_disabled_scoped_provider_does_not_read_unrelated_plugin_details(self):
        self.data['details'] = {'beta@market': ['paused']}
        self.data['rpcErrors'] = {'plugin/read:alpha': {'code': -32600, 'message': 'unavailable'}}
        result = self.collect(kinds={'mcp'}, mcp_plugins={'beta@market'})
        self.assertTrue(result['complete']['mcp'])
        self.assertEqual(result['diagnostics'], [])
        paused = next(item for item in result['items'] if item['plugin'] == 'beta@market')
        self.assertFalse(paused['enabled'])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        reads = [call['params']['pluginName'] for call in calls if call.get('method') == 'plugin/read']
        self.assertEqual(reads, ['beta'])

    def test_scoped_positive_is_known_when_other_installed_plugin_is_disabled(self):
        self.data['details'] = {'alpha@market': ['cloud']}
        self.data['mcps'] = [{'name': 'cloud', 'enabled': True}]
        result = self.collect(kinds={'mcp'}, mcp_plugins={'alpha@market'})
        self.assertTrue(result['complete']['mcp'])
        self.assertEqual([(item['name'], item['plugin'], item['enabled']) for item in result['items']],
                         [('cloud', 'alpha@market', True)])

    def test_scoped_active_owner_checks_competitors_before_claiming_a_match(self):
        self.data['plugins']['installed'][1]['enabled'] = True
        self.data['details'] = {'alpha@market': ['cloud'], 'beta@market': ['cloud']}
        self.data['mcps'] = [{'name': 'cloud', 'enabled': True}]
        result = self.collect(kinds={'mcp'}, mcp_plugins={'alpha@market'})
        self.assertFalse(result['complete']['mcp'])
        self.assertEqual([(item['plugin'], item['enabled']) for item in result['items']],
                         [(None, True), ('alpha@market', None)])
        self.assertIn('codex_mcp_owner_ambiguous', [item['code'] for item in result['diagnostics']])

    def test_absent_scoped_provider_is_complete_without_reading_unrelated_details(self):
        result = self.collect(kinds={'mcp'}, mcp_plugins={'missing@market'})
        self.assertTrue(result['complete']['mcp'])
        self.assertEqual(result['diagnostics'], [])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertNotIn('plugin/read', [call.get('method') for call in calls])


if __name__ == '__main__':
    unittest.main()
