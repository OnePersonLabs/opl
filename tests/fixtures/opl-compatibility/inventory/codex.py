"""Deterministic Codex wire peer; unknown invocations fail instead of being simulated."""

import json
import os
from pathlib import Path
import sys
import time


data = json.loads(Path(os.environ['INVENTORY_FIXTURE']).read_text(encoding='utf-8'))


def record(**values):
    values.update(cwd=os.getcwd(), home=os.environ.get('CODEX_HOME'))
    with Path(os.environ['INVENTORY_CALLS']).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(values) + '\n')


args = sys.argv[1:]
record(args=args)
if args == ['plugin', 'list', '--json']:
    print(json.dumps(data['plugins']))
elif args == ['mcp', 'list', '--json']:
    print(json.dumps(data['mcps']))
elif args == ['app-server', '--listen', 'stdio://']:
    initialized = False
    deferred_response = None
    for line in sys.stdin:
        request = json.loads(line)
        method = request['method']
        record(method=method, params=request.get('params'))
        if data.get('hang') == method:
            time.sleep(60)
        error_key = method + ':' + request.get('params', {}).get('pluginName', '')
        error = data.get('rpcErrors', {}).get(error_key, data.get('rpcErrors', {}).get(method))
        if error:
            print(json.dumps({'id': request['id'], 'error': error}), flush=True)
            continue
        if method == 'initialize':
            response = {'userAgent': 'fake-codex/0.153.4'}
        elif method == 'initialized':
            initialized = True
            continue
        elif not initialized:
            raise SystemExit('request before initialized')
        elif method == 'skills/list':
            assert request['params'] == {'cwds': [os.environ['INVENTORY_CWD']], 'forceReload': True}
            response = data['skills']
        elif method == 'config/read':
            response = data['config']
        elif method == 'plugin/installed':
            response = {'marketplaces': [{'name': 'market', 'path': '/native/marketplace.json',
                         'plugins': [{'id': entry['pluginId'], **entry}
                                     for entry in data['plugins']['installed']]}], 'marketplaceLoadErrors': []}
        elif method == 'plugin/read':
            assert request['params'].get('marketplacePath') == '/native/marketplace.json'
            name = request['params']['pluginName']
            summary = next(entry for entry in data['plugins']['installed'] if entry['name'] == name)
            response = {'plugin': {'marketplaceName': 'market', 'summary': {'id': summary['pluginId'], **summary},
                                   'mcpServers': data.get('details', {}).get(summary['pluginId'], [])}}
        else:
            raise SystemExit('unsupported method: ' + method)
        envelope = {'id': request['id'], 'result': response}
        if method == 'plugin/read' and data.get('reversePluginReads'):
            if deferred_response is None:
                deferred_response = envelope
                continue
            print(json.dumps(envelope), flush=True)
            print(json.dumps(deferred_response), flush=True)
            deferred_response = None
        else:
            print(json.dumps(envelope), flush=True)
else:
    raise SystemExit('unsupported CLI arguments')
