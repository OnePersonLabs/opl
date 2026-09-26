import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { copyFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve, sep } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { codexCommand, pythonBin } from '../../../tools/runtime.mjs'

const repositoryRoot = fileURLToPath(new URL('../../..', import.meta.url))
const driver = join(repositoryRoot, 'tools', 'plugin-dev.mjs')
const sourcePlugin = join(repositoryRoot, 'plugins', 'opl')
const pluginId = 'opl@opl'

function withFakeCodex(run) {
  const root = mkdtempSync(join(tmpdir(), "opl plugin-dev's test-"))
  const fakeCodex = join(root, 'codex.mjs')
  const log = join(root, 'codex-commands.jsonl')
  writeFileSync(fakeCodex, `#!/usr/bin/env node
import { appendFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import readline from 'node:readline'
const args = process.argv.slice(2)
appendFileSync(process.env.FAKE_CODEX_LOG, JSON.stringify(args) + '\\n')
if (args[0] === 'exec') {
  process.stdout.write(JSON.stringify({ type: 'item.completed', item: { type: 'agent_message', text: process.env.FAKE_AGENT_MESSAGE || 'Using $adhd.' } }) + '\\n')
} else if (args[0] === 'app-server') {
  let trusted = false
  const lines = readline.createInterface({ input: process.stdin })
  lines.on('line', (line) => {
    const message = JSON.parse(line)
    const reply = (result) => process.stdout.write(JSON.stringify({ id: message.id, result }) + '\\n')
    if (message.method === 'initialize') reply({})
    if (message.method === 'hooks/list') reply({ data: [{ cwd: process.cwd(), errors: [], warnings: [], hooks: process.env.FAKE_HOOK_PLUGIN_ID ? [{
      pluginId: process.env.FAKE_HOOK_PLUGIN_ID, key: 'plugin:fixture', currentHash: 'fixture-hash',
      enabled: true, trustStatus: trusted ? 'trusted' : 'untrusted', sourcePath: join(process.env.FAKE_INSTALLED_PATH, 'hooks', 'hooks.json'),
    }] : [] }] })
    if (message.method === 'config/batchWrite') {
      appendFileSync(process.env.FAKE_CODEX_LOG, JSON.stringify(['rpc', message.method, message.params.edits]) + '\\n')
      trusted = true
      const filePath = join(process.env.CODEX_HOME, 'config.toml')
      writeFileSync(filePath, '# fixture configuration\\n')
      reply({ filePath, version: '1', status: 'ok' })
    }
  })
} else if (args[0] !== 'plugin') process.exit(91)
else if (args[1] === 'list') {
  const installed = process.env.FAKE_INSTALLED_ID
    ? [{ pluginId: process.env.FAKE_INSTALLED_ID, marketplaceName: 'opl' }]
    : []
  process.stdout.write(JSON.stringify({ installed }))
} else if (args[1] === 'marketplace' && args[2] === 'list') {
  process.stdout.write(JSON.stringify({ marketplaces: [{ name: 'opl', root: ${JSON.stringify(repositoryRoot)} }] }))
} else if (args[1] === 'add') {
  process.stdout.write(JSON.stringify({ installedPath: process.env.FAKE_INSTALLED_PATH }))
} else {
  process.stdout.write('{}')
}
`)
  try {
    run({ root, fakeCodex, log })
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
}

function commands(path) {
  return readFileSync(path, 'utf8').trim().split(/\r?\n/u).filter(Boolean).map((line) => JSON.parse(line))
}

function fixtureRepository(root) {
  const files = {
    '.agents/plugins/marketplace.json': { name: 'fixture-marketplace', plugins: [{ name: 'fixture', source: { source: 'local', path: './plugins/fixture' }, policy: { installation: 'AVAILABLE', authentication: 'ON_INSTALL' }, category: 'Developer Tools' }] },
    'tools/plugin-matrix.json': { schemaVersion: 1, evaluation: { model: 'fixture-model', reasoningEffort: 'high' }, rootUnitRoots: [], plugins: { fixture: { unitRoots: ['tests/unit/fixture'], commands: [] } } },
    'plugins/fixture/.codex-plugin/plugin.json': { name: 'fixture', version: '1.0.0', description: 'Fixture plugin' },
  }
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(resolve(root, path, '..'), { recursive: true })
    writeFileSync(join(root, path), JSON.stringify(content))
  }
  copyFileSync(driver, join(root, 'tools', 'plugin-dev.mjs'))
  copyFileSync(join(repositoryRoot, 'tools', 'runtime.mjs'), join(root, 'tools', 'runtime.mjs'))
  const helpers = 'plugins/opl/skills/refresh-local-plugins/scripts'
  cpSync(join(repositoryRoot, helpers), join(root, helpers), { recursive: true })
  return join(root, 'tools', 'plugin-dev.mjs')
}

test('install-local installs only the selected plugin and runs no verification layer', () => {
  withFakeCodex(({ root, fakeCodex, log }) => {
    const result = spawnSync(process.execPath, [
      driver,
      'install-local',
      '--plugin',
      'opl',
      '--target-home',
      join(root, 'consumer'),
    ], {
      cwd: repositoryRoot,
      encoding: 'utf8',
      env: {
        ...process.env,
        CODEX_BIN: fakeCodex,
        FAKE_CODEX_LOG: log,
        FAKE_INSTALLED_PATH: sourcePlugin,
        FAKE_HOOK_PLUGIN_ID: pluginId,
      },
    })
    assert.equal(result.status, 0, result.stderr)
    assert.match(result.stdout, /the installer adds no tests or skill evaluations[.]/u)
    assert.doesNotMatch(result.stdout, /Contract checks|unit checks|clean installed-copy|PASS .*:/u)
    assert.deepEqual(commands(log).map((args) => args.slice(0, 2)), [
      ['plugin', 'marketplace'],
      ['plugin', 'add'],
      ['app-server', '--stdio'],
      ['rpc', 'config/batchWrite'],
    ])
  })
})

test('install-local without a plugin leaves absent installs untouched', () => {
  withFakeCodex(({ root, fakeCodex, log }) => {
    const result = spawnSync(process.execPath, [driver, 'install-local', '--target-home', join(root, 'consumer')], {
      encoding: 'utf8',
      env: { ...process.env, CODEX_BIN: fakeCodex, FAKE_CODEX_LOG: log, FAKE_INSTALLED_PATH: sourcePlugin },
    })
    assert.equal(result.status, 0, result.stderr)
    assert.match(result.stdout, /No modified plugins/u)
    assert.equal(existsSync(log), false, 'no modified installs must not invoke Codex')
  })
})

for (const layout of ['global', 'local']) {
  test(`Codex npm ${layout} shims resolve through PATH and preserve literal arguments`, () => {
    withFakeCodex(({ root }) => {
      const bin = join(root, 'node_modules', '@openai', 'codex', 'bin')
      const shimDirectory = layout === 'global' ? root : join(root, 'node_modules', '.bin')
      mkdirSync(bin, { recursive: true })
      mkdirSync(shimDirectory, { recursive: true })
      writeFileSync(join(shimDirectory, 'codex.cmd'), '@exit /b 91\n')
      writeFileSync(join(bin, 'codex.js'), 'process.stdout.write(JSON.stringify(process.argv.slice(2)))\n')
      const args = ['a path with spaces', 'literal & | < > $() ` " apostrophe\' %PATH%']
      const [executable, ...commandArgs] = codexCommand(args, { platform: 'win32', env: { Path: shimDirectory } })
      const result = spawnSync(executable, commandArgs, { encoding: 'utf8' })
      assert.equal(result.status, 0, result.stderr)
      assert.deepEqual(JSON.parse(result.stdout), args)
    })
  })
}

test('Python selection follows the native platform and accepts an explicit interpreter', () => {
  assert.equal(pythonBin({}, 'win32'), 'python')
  assert.equal(pythonBin({}, 'linux'), 'python3')
  assert.equal(pythonBin({ PYTHON_BIN: 'custom interpreter' }, 'win32'), 'custom interpreter')
})

test('focus retains the running Node interpreter without depending on PATH', () => {
  withFakeCodex(({ root }) => {
    const file = join(root, 'runtime.test.mjs')
    const marker = join(root, 'runtime-result.txt')
    writeFileSync(file, "import assert from 'node:assert/strict'\nimport { writeFileSync } from 'node:fs'\nassert.equal(process.execPath, process.env.EXPECTED_NODE)\nwriteFileSync(process.env.RUNTIME_RESULT, process.execPath)\n")
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => key.toLowerCase() !== 'path' && key !== 'NODE_TEST_CONTEXT'))
    const result = spawnSync(process.execPath, [driver, 'focus', '--file', file], {
      cwd: repositoryRoot,
      encoding: 'utf8',
      env: { ...env, PATH: '', EXPECTED_NODE: process.execPath, RUNTIME_RESULT: marker },
    })
    assert.equal(result.status, 0, result.stderr)
    assert.equal(readFileSync(marker, 'utf8'), process.execPath)
  })
})

test('unit discovers nested Python tests using native paths in a repository with spaces', () => {
  withFakeCodex(({ root }) => {
    const fixtureDriver = fixtureRepository(root)
    const tests = join(root, 'tests', 'unit', 'fixture', 'nested')
    mkdirSync(tests, { recursive: true })
    writeFileSync(join(tests, 'test_probe.py'), "print('nested Python test executed')\n")
    const result = spawnSync(process.execPath, [fixtureDriver, 'unit', '--plugin', 'fixture'], { encoding: 'utf8' })
    assert.equal(result.status, 0, result.stderr)
    assert.match(result.stdout, /nested Python test executed/u)
  })
})

test('contract validates default and Windows hook targets using either path separator', () => {
  withFakeCodex(({ root }) => {
    const fixtureDriver = fixtureRepository(root)
    const plugin = join(root, 'plugins', 'fixture')
    const manifestPath = join(plugin, '.codex-plugin', 'plugin.json')
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    manifest.hooks = './hooks/hooks.json'
    writeFileSync(manifestPath, JSON.stringify(manifest))
    mkdirSync(join(plugin, 'scripts'))
    mkdirSync(join(plugin, 'hooks'))
    writeFileSync(join(plugin, 'scripts', 'default.py'), '# default hook\n')
    writeFileSync(join(plugin, 'scripts', 'windows.py'), '# Windows hook\n')
    const handler = { type: 'command', command: 'python3 "${PLUGIN_ROOT}/scripts/default.py"', commandWindows: 'python "${PLUGIN_ROOT}\\scripts\\windows.py"' }
    const hookPath = join(plugin, 'hooks', 'hooks.json')
    const writeHooks = () => writeFileSync(hookPath, JSON.stringify({ hooks: { SessionStart: [{ hooks: [handler] }] } }))
    writeHooks()
    const runContract = () => spawnSync(process.execPath, [fixtureDriver, 'contract', '--plugin', 'fixture'], { encoding: 'utf8' })
    const valid = runContract()
    assert.equal(valid.status, 0, valid.stderr)
    handler.commandWindows = 'python "${PLUGIN_ROOT}/scripts/missing.py"'
    writeHooks()
    const invalid = runContract()
    assert.equal(invalid.status, 1)
    assert.match(invalid.stderr, /hook commandWindows target is missing/u)
  })
})

test('contract accepts Codex skill metadata without a second invocation frontmatter field', () => {
  withFakeCodex(({ root }) => {
    const fixtureDriver = fixtureRepository(root)
    const plugin = join(root, 'plugins', 'fixture')
    const manifestPath = join(plugin, '.codex-plugin', 'plugin.json')
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    manifest.skills = './skills'
    writeFileSync(manifestPath, JSON.stringify(manifest))
    const skill = join(plugin, 'skills', 'fixture-skill')
    mkdirSync(join(skill, 'agents'), { recursive: true })
    writeFileSync(join(skill, 'SKILL.md'), '---\nname: fixture-skill\ndescription: A Codex-only fixture skill.\n---\n')
    writeFileSync(join(skill, 'agents', 'openai.yaml'), 'policy:\n  allow_implicit_invocation: false\n')
    const cases = join(root, 'tests', 'evals', 'cases')
    mkdirSync(cases, { recursive: true })
    writeFileSync(join(cases, 'fixture.jsonl'), [
      { id: 'fixture-skill:direct', skill: 'fixture-skill', kind: 'direct', should_activate: true },
      { id: 'fixture-skill:indirect', skill: 'fixture-skill', kind: 'indirect', should_activate: false },
      { id: 'fixture-skill:negative', skill: 'fixture-skill', kind: 'negative', should_activate: false },
    ].map((item) => JSON.stringify(item)).join('\n') + '\n')
    const result = spawnSync(process.execPath, [fixtureDriver, 'contract', '--plugin', 'fixture'], { encoding: 'utf8' })
    assert.equal(result.status, 0, result.stderr)
  })
})

test('eval prepares readable skill links and launches a JS Codex fixture', () => {
  withFakeCodex(({ root, fakeCodex, log }) => {
    const result = spawnSync(process.execPath, [driver, 'eval', '--plugin', 'opl', '--skill', 'adhd', '--case', 'adhd:direct'], {
      cwd: repositoryRoot,
      encoding: 'utf8',
      env: { ...process.env, CODEX_BIN: fakeCodex, FAKE_CODEX_LOG: log, OPL_PLUGIN_DEV_STATE: join(root, 'state') },
    })
    assert.equal(result.status, 0, result.stderr)
    assert.match(result.stdout, /PASS adhd:direct/u)
    const args = commands(log)[0]
    assert.equal(args[args.indexOf('--sandbox') + 1], 'read-only')
    if (process.platform === 'win32') {
      const overrides = args.flatMap((argument, index) => argument === '-c' ? [args[index + 1]] : [])
      assert.ok(overrides.includes('windows.sandbox="unelevated"'), 'Windows read-only evaluations must avoid administrator sandbox setup')
    }
    const host = args[args.indexOf('-C') + 1]
    assert.equal(realpathSync(join(host, '.agents', 'skills', 'adhd')), realpathSync(join(sourcePlugin, 'skills', 'adhd')))
  })
})

for (const [label, response, activated] of [
  ['another skill with a later workflow mention', 'I’m using the **humanizer** skill because the Unslop workflow is about making drafted prose sound direct.', false],
  ['manual-only namespaced invocation', 'I’m using the requested manual-only **`$opl:unslop`** skill.', true],
  ['Markdown around the article and skill', 'I’m applying **the `$unslop` skill** now.', true],
  ['explicitly selected skill', 'I’m using the explicitly selected `unslop` skill to identify its first workflow step.', true],
  ['explicitly requested skill', 'I’m using the explicitly requested `unslop` skill to identify its first workflow step.', true],
  ['conditional namespaced selection', 'I’d use the `opl:unslop` skill.', true],
  ['conditional selection with straight apostrophe', "I'd use `$unslop`.", true],
  ['expanded conditional selection', 'I would use the `unslop` skill.', true],
  ['future namespaced selection', 'I’ll use `opl:unslop`.', true],
  ['future selection with straight apostrophe', "I'll use `$unslop`.", true],
  ['expanded future selection', 'I will use the `unslop` skill.', true],
  ['negated future selection', 'I will not use the `unslop` skill.', false],
  ['negated conditional selection', 'I would not use the `unslop` skill.', false],
  ['another conditional skill with a later target mention', 'I’d use `humanizer` because the unslop workflow is unavailable.', false],
  ['another explicitly selected skill with a later target mention', 'I’m using the explicitly selected `humanizer` skill because the unslop workflow is unavailable.', false],
]) {
  test(`eval matches the announced skill target: ${label}`, () => {
    withFakeCodex(({ root, fakeCodex, log }) => {
      const fixtureDriver = fixtureRepository(root)
      const manifestPath = join(root, 'plugins', 'fixture', '.codex-plugin', 'plugin.json')
      const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
      manifest.skills = './skills/'
      writeFileSync(manifestPath, JSON.stringify(manifest))
      const skill = join(root, 'plugins', 'fixture', 'skills', 'unslop')
      mkdirSync(skill, { recursive: true })
      writeFileSync(join(skill, 'SKILL.md'), '---\nname: unslop\ndescription: Correct a workflow mistake.\n---\n')
      const cases = join(root, 'tests', 'evals', 'cases')
      mkdirSync(cases, { recursive: true })
      writeFileSync(join(cases, 'fixture.jsonl'), JSON.stringify({ id: 'unslop:direct', skill: 'unslop', kind: 'direct', prompt: 'Use $unslop.', should_activate: true }) + '\n')
      const result = spawnSync(process.execPath, [fixtureDriver, 'eval', '--plugin', 'fixture', '--skill', 'unslop'], {
        encoding: 'utf8',
        env: { ...process.env, CODEX_BIN: fakeCodex, FAKE_CODEX_LOG: log, FAKE_AGENT_MESSAGE: response, OPL_PLUGIN_DEV_STATE: join(root, 'state') },
      })
      assert.equal(result.status, activated ? 0 : 1, result.stderr)
      const receipt = JSON.parse(readFileSync(join(root, '.work', 'eval-results', 'fixture.json'), 'utf8'))[0]
      assert.equal(receipt.activated, activated)
    })
  })
}

test('installed package discovery launches the Codex app-server without a shell', () => {
  withFakeCodex(({ root, fakeCodex, log }) => {
    const name = 'opl'
    const result = spawnSync(process.execPath, [driver, 'installed', '--plugin', name, '--package-only'], {
      cwd: repositoryRoot,
      encoding: 'utf8',
      env: {
        ...process.env,
        CODEX_BIN: fakeCodex,
        FAKE_CODEX_LOG: log,
        FAKE_INSTALLED_PATH: join(repositoryRoot, 'plugins', name),
        FAKE_HOOK_PLUGIN_ID: `${name}@opl`,
        OPL_PLUGIN_DEV_STATE: join(root, 'state'),
      },
    })
    assert.equal(result.status, 0, result.stderr)
    assert.match(result.stdout, /package\/discovery only/u)
    assert.ok(commands(log).some((args) => args[0] === 'app-server' && args[1] === '--stdio'))
    assert.equal(commands(log).at(-1)[1], 'config/batchWrite')
  })
})

test('the default installed checkpoint tests and trusts selected hooks without interactive onboarding', () => {
  withFakeCodex(({ root, fakeCodex, log }) => {
    const fixtureDriver = fixtureRepository(root)
    const plugin = join(root, 'plugins', 'fixture')
    const manifestPath = join(plugin, '.codex-plugin', 'plugin.json')
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    manifest.hooks = './hooks/hooks.json'
    writeFileSync(manifestPath, JSON.stringify(manifest))
    mkdirSync(join(plugin, 'scripts'))
    mkdirSync(join(plugin, 'hooks'))
    writeFileSync(join(plugin, 'scripts', 'hook.mjs'), "process.stdout.write('{}')\n")
    writeFileSync(join(plugin, 'hooks', 'hooks.json'), JSON.stringify({
      hooks: { SessionStart: [{ hooks: [{ type: 'command', command: 'node "${PLUGIN_ROOT}/scripts/hook.mjs"' }] }] },
    }))
    const unitRoot = join(root, 'tests', 'unit', 'fixture')
    mkdirSync(unitRoot, { recursive: true })
    writeFileSync(join(unitRoot, 'executed.test.mjs'), "import { writeFileSync } from 'node:fs'\nwriteFileSync(process.env.UNIT_MARKER, 'executed')\n")
    const marker = join(root, 'unit-marker.txt')
    const result = spawnSync(process.execPath, [fixtureDriver, 'installed', '--plugin', 'fixture'], {
      encoding: 'utf8',
      env: {
        ...Object.fromEntries(Object.entries(process.env).filter(([key]) => key !== 'NODE_TEST_CONTEXT')),
        CODEX_BIN: fakeCodex,
        FAKE_CODEX_LOG: log,
        FAKE_INSTALLED_PATH: plugin,
        FAKE_HOOK_PLUGIN_ID: 'fixture@fixture-marketplace',
        OPL_PLUGIN_DEV_STATE: join(root, 'fresh-state'),
        UNIT_MARKER: marker,
      },
    })
    assert.equal(result.status, 0, result.stderr)
    assert.equal(readFileSync(marker, 'utf8'), 'executed')
    assert.match(result.stdout, /clean installed-copy checkpoint passed/u)
    assert.deepEqual(commands(log), [
      ['plugin', 'list', '--json'],
      ['plugin', 'marketplace', 'list', '--json'],
      ['plugin', 'marketplace', 'add', root + sep, '--json'],
      ['plugin', 'add', 'fixture@fixture-marketplace', '--json'],
      ['app-server', '--stdio'],
      ['rpc', 'config/batchWrite', [{ keyPath: 'hooks.state', value: { 'plugin:fixture': { trusted_hash: 'fixture-hash' } }, mergeStrategy: 'upsert' }]],
    ])
  })
})
