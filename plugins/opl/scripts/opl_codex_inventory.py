"""Read-only Codex inventory for the advisory compatibility checker.

Uses native metadata queries only: never creates a thread or starts an MCP server.
Raw CLI output, transports, config values, and server error text are not returned.
The plugin/installed and plugin/read wire contracts are experimental and were
verified against Codex 0.153.4; unsupported or inconsistent metadata stays unknown.
"""

import errno
import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time


class InventoryError(Exception):
    """A sanitized, structured discovery failure."""

    def __init__(self, code, message, *, transient=False):
        super().__init__(message)
        self.code = code
        self.transient = transient


def _command():
    executable = os.environ.get('CODEX_BIN', 'codex')
    path = Path(shutil.which(executable) or executable)
    if path.is_file():
        path = path.resolve()
    suffix = path.suffix.lower()
    if suffix == '.py':
        return [sys.executable, '-B', '-X', 'utf8', str(path.resolve())]
    if os.name == 'nt' and suffix in ('.cmd', '.bat', '.ps1', ''):
        candidates = [path.parent.parent / '@openai/codex/bin/codex.js',
                      path.parent / 'node_modules/@openai/codex/bin/codex.js',
                      path.parent / 'bin/codex.js']
        entrypoint = next((entry for entry in candidates if entry.is_file()), None)
        if entrypoint:
            path, suffix = entrypoint, '.js'
        elif suffix:
            raise InventoryError('codex_unsupported_launcher',
                                 'Set CODEX_BIN to the native Codex executable or its JavaScript entrypoint.')
    if suffix in ('.js', '.mjs', '.cjs'):
        return [os.environ.get('NODE_BIN', 'node'), str(path.resolve())]
    return [str(path)]


def _start(command, cwd, environment):
    options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} \
        if os.name == 'nt' else {'start_new_session': True}
    try:
        return subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding='utf-8', errors='replace', **options)
    except OSError as error:
        raise InventoryError('codex_launch_failed',
                             'Could not launch Codex; check CODEX_BIN and the selected working directory.',
                             transient=error.errno in (errno.EAGAIN, errno.EINTR, errno.ETXTBSY)) from error


def _stop(process):
    if process.poll() is None:
        if os.name == 'nt':
            # Kill the npm launcher and its native child together, without a shell.
            try:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=3, check=False)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    for stream in (process.stdin, process.stdout):
        if stream:
            stream.close()


def _decode(value):
    try:
        return json.loads(value)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise InventoryError('codex_invalid_json', 'Codex returned invalid JSON metadata.') from error


def _cli(command, args, cwd, environment, timeout):
    process = _start(command + args, cwd, environment)
    try:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise InventoryError('codex_query_timeout', 'Codex metadata query timed out.', transient=True) from error
        if process.returncode:
            raise InventoryError('codex_query_failed', 'Codex metadata command exited unsuccessfully.')
        return _decode(output)
    finally:
        _stop(process)


class _AppServer:
    def __init__(self, command, cwd, environment):
        self.process = _start(command + ['app-server', '--listen', 'stdio://'], cwd, environment)
        self.messages = queue.Queue()
        self.identifier = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(line)
        except (OSError, ValueError):
            # Shutdown closes the stream. The consumer receives EOF in either case.
            pass
        finally:
            self.messages.put(None)

    def send(self, payload):
        try:
            self.process.stdin.write(json.dumps(payload) + '\n')
            self.process.stdin.flush()
        except (OSError, ValueError) as error:
            raise InventoryError('codex_rpc_closed', 'Codex app-server closed its input.', transient=True) from error

    def request(self, method, params, timeout):
        result = self.request_many([('single', method, params)], timeout)['single']
        if isinstance(result, InventoryError):
            raise result
        return result

    def request_many(self, requests, timeout):
        """Pipeline independent metadata reads and retain successes when one fails."""
        pending, results = {}, {}
        for key, method, params in requests:
            self.identifier += 1
            pending[self.identifier] = key
            self.send({'id': self.identifier, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while pending:
            try:
                line = self.messages.get(timeout=max(0, deadline - time.monotonic()))
                if line is None:
                    raise InventoryError('codex_rpc_closed', 'Codex app-server exited before returning metadata.', transient=True)
                message = _decode(line)
                if not isinstance(message, dict):
                    raise InventoryError('codex_invalid_response', 'Codex app-server returned a non-object message.')
                identifier = message.get('id')
                if not isinstance(identifier, (int, str)) or identifier not in pending:
                    if 'id' not in message and isinstance(message.get('method'), str):
                        continue
                    raise InventoryError('codex_invalid_response', 'Codex app-server returned an unexpected response identifier.')
            except (queue.Empty, InventoryError) as error:
                if isinstance(error, queue.Empty):
                    error = InventoryError('codex_query_timeout', 'Codex metadata query timed out.', transient=True)
                results.update({key: error for key in pending.values()})
                break
            key = pending.pop(identifier)
            if 'error' in message:
                error = message['error']
                code = error.get('code') if isinstance(error, dict) else None
                results[key] = InventoryError('codex_rpc_unsupported' if code == -32601 else 'codex_rpc_error',
                                              'Codex app-server rejected the metadata request.', transient=code == -32603)
            elif message.get('result') is None:
                results[key] = InventoryError('codex_invalid_response', 'Codex app-server response omitted its result.')
            else:
                results[key] = message['result']
        return results

    def close(self):
        _stop(self.process)
        self.reader.join(timeout=1)


def _object(value):
    if not isinstance(value, dict):
        raise InventoryError('codex_invalid_response', 'Codex metadata entry must be an object.')
    return value


def _array(value):
    if not isinstance(value, list):
        raise InventoryError('codex_invalid_response', 'Codex metadata collection must be an array.')
    return value


def _name(value):
    if not isinstance(value, str) or not value:
        raise InventoryError('codex_invalid_response', 'Codex metadata entry omitted its identity.')
    return value


def _enabled(value):
    if value is not None and not isinstance(value, bool):
        raise InventoryError('codex_invalid_response', 'Codex metadata enabled state must be boolean or null.')
    return value


def collect_inventory(cwd: Path, *, codex_home: Path | None = None, timeout: float = 20.0,
                      kinds: set[str] | None = None, mcp_plugins: set[str] | None = None) -> dict:
    """Collect metadata with a shared deadline and explicit partial results.

    ``kinds=None`` requests all kinds; an empty set starts no process.
    ``mcp_plugins=None`` inventories every plugin's MCP declarations. An empty
    set requests only native MCP names and states. A nonempty set limits output
    to those owners, reading other enabled declarations only when needed to
    detect name collisions before attributing an active server.
    """
    result = {'items': [], 'complete': {'plugin': False, 'skill': False, 'mcp': False},
              'diagnostics': [], 'watchPaths': []}
    requested = {'plugin', 'skill', 'mcp'} if kinds is None else set(kinds)
    if requested - {'plugin', 'skill', 'mcp'}:
        raise ValueError('kinds must contain only plugin, skill, or mcp')
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be a positive finite number')
    if not requested:
        return result
    cwd = Path(cwd).resolve()
    environment = os.environ.copy()
    if codex_home is not None:
        environment['CODEX_HOME'] = str(Path(codex_home).resolve())
    deadline = time.monotonic() + timeout

    def diagnostic(error, kind=None, **fields):
        item = {'code': error.code, 'message': str(error), **fields}
        if kind:
            item['kind'] = kind
        result['diagnostics'].append(item)

    try:
        command = _command()
    except InventoryError as error:
        diagnostic(error)
        return result

    def query(operation, kind, callback, **fields):
        for attempt in (1, 2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                diagnostic(InventoryError('codex_query_timeout', 'Codex inventory time budget was exhausted.'),
                           kind, operation=operation, **fields)
                return None
            try:
                value = callback(remaining / (3 - attempt))
                if value is None:
                    raise InventoryError('codex_invalid_response', 'Codex metadata query returned a null result.')
                return value
            except InventoryError as error:
                if error.transient and attempt == 1:
                    result['diagnostics'].append({'code': 'codex_query_retry',
                                                  'message': 'Retrying a transient Codex metadata failure.',
                                                  'kind': kind, 'operation': operation, 'cause': error.code, **fields})
                    continue
                diagnostic(error, kind, operation=operation, **fields)
                return None

    plugins = query('plugin/list', 'plugin', lambda seconds: _cli(command, ['plugin', 'list', '--json'],
                                                                cwd, environment, seconds)) if 'plugin' in requested else None
    if plugins is not None:
        try:
            for entry in _array(_object(plugins).get('installed')):
                entry = _object(entry)
                if entry.get('installed') is False:
                    continue
                identity = _name(entry.get('pluginId'))
                result['items'].append({'kind': 'plugin', 'name': _name(entry.get('name')), 'id': identity,
                                        'plugin': identity, 'enabled': _enabled(entry.get('enabled'))})
            result['complete']['plugin'] = True
        except InventoryError as error:
            diagnostic(error, 'plugin')

    mcps = query('mcp/list', 'mcp', lambda seconds: _cli(command, ['mcp', 'list', '--json'],
                                                      cwd, environment, seconds)) if 'mcp' in requested else None
    if mcps is not None:
        try:
            for entry in _array(mcps):
                entry = _object(entry)
                name = _name(entry.get('name'))
                item = {'kind': 'mcp', 'name': name, 'id': 'mcp:' + name,
                        'enabled': _enabled(entry.get('enabled')), 'plugin': None}
                if isinstance(entry.get('disabled_reason'), str):
                    item['reason'] = entry['disabled_reason']
                result['items'].append(item)
            result['complete']['mcp'] = True
        except InventoryError as error:
            diagnostic(error, 'mcp')

    server = None

    def connect(seconds):
        nonlocal server
        started = time.monotonic()
        if server is None:
            server = _AppServer(command, cwd, environment)
            _object(server.request('initialize', {'clientInfo': {'name': 'opl_compatibility', 'version': '1.0.0'},
                                                  'capabilities': {'experimentalApi': True}}, seconds))
            server.send({'method': 'initialized'})
        return max(0, seconds - (time.monotonic() - started))

    def rpc(method, params, seconds):
        nonlocal server
        try:
            seconds = connect(seconds)
            return server.request(method, params, seconds)
        except InventoryError as error:
            if server and error.code not in ('codex_rpc_error', 'codex_rpc_unsupported'):
                server.close()
                server = None
            raise

    skills = query('skills/list', 'skill', lambda seconds: rpc('skills/list',
                   {'cwds': [str(cwd)], 'forceReload': True}, seconds)) if 'skill' in requested else None
    if skills is not None:
        try:
            records = _array(_object(skills).get('data'))
            if len(records) != 1 or Path(_name(_object(records[0]).get('cwd'))).resolve() != cwd:
                raise InventoryError('codex_invalid_response', 'Codex skills response did not identify the requested working directory.')
            record = records[0]
            provenance_complete = True
            for entry in _array(record.get('skills')):
                entry = _object(entry)
                qualified_name = _name(entry.get('name'))
                path = _name(entry.get('path'))
                if 'pluginId' not in entry:
                    provenance_complete = False
                    diagnostic(InventoryError('codex_skill_provenance_unavailable',
                                              'Codex skill metadata omitted pluginId; ownership cannot be determined.'),
                               'skill', path=path)
                    continue
                plugin = entry['pluginId']
                if plugin is not None:
                    plugin = _name(plugin)
                name = qualified_name
                if plugin and name.startswith(plugin.split('@', 1)[0] + ':'):
                    name = name.split(':', 1)[1]
                result['items'].append({'kind': 'skill', 'name': name, 'qualifiedName': qualified_name,
                                        'id': 'skill:' + (plugin or '') + ':' + path,
                                        'plugin': plugin, 'path': path, 'enabled': _enabled(entry.get('enabled'))})
                result['watchPaths'].extend([path, str(Path(path).parent), str(Path(path).parent.parent)])
            errors = _array(record.get('errors'))
            result['complete']['skill'] = not errors and provenance_complete
            if errors:
                diagnostic(InventoryError('codex_skill_load_errors', 'Codex reported errors while loading skills.'),
                           'skill', count=len(errors))
        except InventoryError as error:
            diagnostic(error, 'skill')

    config_kind = 'mcp' if 'mcp' in requested else ('skill' if 'skill' in requested else 'plugin')
    config_result = query('config/read', config_kind, lambda seconds: rpc('config/read',
                          {'includeLayers': True, 'cwd': str(cwd)}, seconds))
    metadata_complete = result['complete']['plugin'] if 'plugin' in requested else True
    configured_names = set()
    claims = []
    try:
        config = _object(_object(config_result).get('config'))
        configured_names = set(_object(config.get('mcp_servers', {})))
        for layer in _array(config_result.get('layers', [])):
            source = _object(layer).get('name', {})
            if isinstance(source, dict) and isinstance(source.get('file'), str):
                result['watchPaths'].append(source['file'])
            if isinstance(source, dict) and isinstance(source.get('dotCodexFolder'), str):
                result['watchPaths'].append(str(Path(source['dotCodexFolder']) / 'config.toml'))
    except InventoryError as error:
        metadata_complete = False
        if config_result is not None:
            diagnostic(error, config_kind, operation='config/read')

    result['watchPaths'] = sorted(set(result['watchPaths']))
    if 'mcp' not in requested or mcp_plugins == set():
        if server:
            server.close()
        return result

    # These metadata methods are experimental in Codex 0.153.4. Keep their wire
    # dependency here instead of reproducing Codex's installed-cache loader.
    installed = query('plugin/installed', 'mcp', lambda seconds: rpc('plugin/installed',
                      {'cwds': [str(cwd)]}, seconds))

    providers = []
    try:
        installed = _object(installed)
        errors = _array(installed.get('marketplaceLoadErrors'))
        if errors:
            metadata_complete = False
            diagnostic(InventoryError('codex_marketplace_load_errors',
                                      'Codex could not load every installed marketplace.'), 'mcp', count=len(errors))
        for marketplace in _array(installed.get('marketplaces')):
            marketplace = _object(marketplace)
            marketplace_name = _name(marketplace.get('name'))
            marketplace_path = marketplace.get('path')
            for plugin in _array(marketplace.get('plugins')):
                plugin = _object(plugin)
                if plugin.get('installed') is not True:
                    continue
                identity = _name(plugin.get('id'))
                name = _name(plugin.get('name'))
                if identity != name + '@' + marketplace_name:
                    raise InventoryError('codex_invalid_response', 'Codex plugin identity disagrees with its marketplace.')
                params = {'pluginName': name}
                if marketplace_path is not None:
                    params['marketplacePath'] = _name(marketplace_path)
                else:
                    params['remoteMarketplaceName'] = marketplace_name
                providers.append((identity, _enabled(plugin.get('enabled')), params))
    except InventoryError as error:
        metadata_complete = False
        if installed is not None:
            diagnostic(error, 'mcp', operation='plugin/installed')

    expected_providers = {item['id'] for item in result['items'] if item['kind'] == 'plugin'}
    if 'plugin' in requested and expected_providers != {provider[0] for provider in providers}:
        metadata_complete = False
        diagnostic(InventoryError('codex_plugin_inventory_changed',
                                  'Codex plugin inventory differed between metadata queries.'), 'mcp')
    unverified_competitors = set()
    scope = None if mcp_plugins is None else set(mcp_plugins)

    def provider_error(error, identity):
        nonlocal metadata_complete
        metadata_complete = False
        if scope is None or identity in scope:
            diagnostic(error, 'mcp', operation='plugin/read', plugin=identity)
        else:
            unverified_competitors.add(identity)

    def read_providers(batch):
        nonlocal server, metadata_complete
        pending = {identity: params for identity, _, params in batch}
        details = {}
        for attempt in (1, 2):
            if not pending:
                break
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise InventoryError('codex_query_timeout', 'Codex inventory time budget was exhausted.')
                seconds = connect(remaining / (3 - attempt))
                responses = server.request_many([(identity, 'plugin/read', params)
                                                 for identity, params in pending.items()], seconds)
            except InventoryError as error:
                responses = {identity: error for identity in pending}
            retry = {}
            reset = False
            for identity, detail in responses.items():
                if isinstance(detail, InventoryError):
                    reset |= detail.code not in ('codex_rpc_error', 'codex_rpc_unsupported')
                    if detail.transient and attempt == 1:
                        if scope is None or identity in scope:
                            result['diagnostics'].append({'code': 'codex_query_retry',
                                'message': 'Retrying a transient Codex metadata failure.', 'kind': 'mcp',
                                'operation': 'plugin/read', 'plugin': identity, 'cause': detail.code})
                        retry[identity] = pending[identity]
                    else:
                        provider_error(detail, identity)
                else:
                    details[identity] = detail
            if reset and server:
                server.close()
                server = None
            pending = retry
        for identity, enabled, _ in batch:
            if identity not in details:
                continue
            try:
                plugin = _object(_object(details[identity]).get('plugin'))
                summary = _object(plugin.get('summary'))
                if summary.get('id') != identity or summary.get('installed') is not True:
                    raise InventoryError('codex_invalid_response', 'Codex plugin details did not identify the installed plugin.')
                detail_enabled = _enabled(summary.get('enabled'))
                if detail_enabled != enabled:
                    enabled = None
                    provider_error(InventoryError('codex_plugin_inventory_changed',
                                                   'Codex plugin enablement changed between metadata queries.'), identity)
                for name in _array(plugin.get('mcpServers')):
                    claims.append({'kind': 'mcp', 'name': _name(name), 'id': 'mcp:' + identity + ':' + name,
                                   'plugin': identity, 'enabled': enabled})
            except InventoryError as error:
                provider_error(error, identity)

    selected = providers if scope is None else [provider for provider in providers if provider[0] in scope]
    read_providers(selected)
    native_mcps = {item['name']: item for item in result['items'] if item['kind'] == 'mcp'}
    if scope is not None and any(claim['enabled'] is not False and claim['name'] in native_mcps
                                 and claim['name'] not in configured_names for claim in claims):
        # Only a potentially active target needs competing plugin declarations.
        # Disabled/shadowed targets and absent plugins need no unrelated reads.
        read_providers([provider for provider in providers if provider[0] not in scope and provider[1] is not False])
    if unverified_competitors:
        diagnostic(InventoryError('codex_mcp_ownership_incomplete',
                                  'Codex could not verify competing plugin declarations for the requested MCP owner.'),
                   'mcp', count=len(unverified_competitors))

    if server:
        server.close()

    native_mcps = {item['name']: item for item in result['items'] if item['kind'] == 'mcp'}
    contenders = {}
    for claim in claims:
        if claim['enabled'] is not False:
            contenders.setdefault(claim['name'], []).append(claim)
    replacements = set()
    native_complete = result['complete']['mcp']
    for claim in claims:
        if scope is not None and claim['plugin'] not in scope:
            continue
        name = claim['name']
        if claim['enabled'] is False:
            claim['reason'] = 'owning plugin is disabled'
        elif name in configured_names:
            # Codex catalog Config precedence is above Plugin precedence.
            claim['enabled'] = False
            claim['reason'] = 'shadowed by a configured MCP server'
        elif not metadata_complete or claim['enabled'] is None:
            claim['enabled'] = None
            claim['reason'] = 'plugin MCP ownership metadata is incomplete'
        elif len(contenders[name]) > 1:
            claim['enabled'] = None
            claim['reason'] = 'multiple enabled plugins declare this MCP server'
            result['complete']['mcp'] = False
            diagnostic(InventoryError('codex_mcp_owner_ambiguous',
                                      'Codex metadata does not identify the winning plugin for an MCP name collision.'),
                       'mcp', plugin=claim['plugin'], name=name)
        elif name in native_mcps:
            claim['enabled'] = native_mcps[name]['enabled']
            if 'reason' in native_mcps[name]:
                claim['reason'] = native_mcps[name]['reason']
            replacements.add(name)
        elif native_complete:
            claim['enabled'] = False
            claim['reason'] = 'plugin MCP server is absent from Codex configured servers'
        else:
            claim['enabled'] = None
            claim['reason'] = 'Codex configured MCP server inventory is unavailable'
        result['items'].append(claim)
    result['items'] = [item for item in result['items']
                       if not (item['kind'] == 'mcp' and item['plugin'] is None and item['name'] in replacements)]
    result['complete']['mcp'] = result['complete']['mcp'] and metadata_complete
    result['watchPaths'] = sorted(set(result['watchPaths']))
    return result
