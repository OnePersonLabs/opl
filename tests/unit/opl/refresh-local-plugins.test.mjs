import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { counterpartInvocation } from '../../../plugins/opl/skills/refresh-local-plugins/scripts/install-local.mjs'

const scripts = fileURLToPath(new URL('../../../plugins/opl/skills/refresh-local-plugins/scripts', import.meta.url))
const oplScripts = fileURLToPath(new URL('../../../plugins/opl/scripts', import.meta.url))

function writeJson(path, value) {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify(value))
}

function fixture(t, manifest = '.agents/plugins/marketplace.json') {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "refresh plugin's test-")))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const repo = join(root, 'another marketplace')
  const home = join(root, 'consumer home')
  const userProfile = join(root, 'isolated user')
  mkdirSync(join(userProfile, '.codex'), { recursive: true })
  const log = join(root, 'commands.jsonl')
  const registration = join(root, 'marketplaces.json')
  const selected = join(home, 'plugins', 'cache', 'example-market', 'alpha', '1.0.0')
  const helper = join(selected, 'skills', 'refresh-local-plugins', 'scripts', 'install-local.mjs')
  // Use a copied, installed helper. There are no repository drivers or npm files.
  cpSync(scripts, dirname(helper), { recursive: true })
  const entries = ['alpha', 'beta'].map((name) => ({ name, source: { source: 'local', path: `./components/${name}` } }))
  const marketplacePath = join(repo, manifest)
  writeJson(marketplacePath, { name: 'example-market', plugins: entries })
  for (const { name } of entries) {
    writeJson(join(repo, 'components', name, '.codex-plugin', 'plugin.json'), { name, version: '1.0.0', description: `${name} fixture` })
    writeFileSync(join(repo, 'components', name, 'content.txt'), `${name} new bytes`)
  }
  const sibling = join(home, 'plugins', 'cache', 'unrelated', 'other', '1.0.0', 'content.txt')
  mkdirSync(dirname(sibling), { recursive: true })
  writeFileSync(sibling, 'leave me alone')
  writeJson(registration, [])
  const fakeCodex = join(root, 'codex.mjs')
  writeFileSync(fakeCodex, `
import { appendFileSync, cpSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import readline from 'node:readline'
const args = process.argv.slice(2)
const env = process.env
const home = env.CODEX_HOME
appendFileSync(env.COMMAND_LOG, JSON.stringify({ args, home, cwd: process.cwd() }) + '\\n')
const out = (value) => process.stdout.write(JSON.stringify(value))
if (args.join(' ') === 'app-server --stdio') {
  readline.createInterface({ input: process.stdin }).on('line', (line) => {
    const message = JSON.parse(line)
    if (message.method === 'initialize') out({ id: message.id, result: {} }), process.stdout.write('\\n')
    else if (message.method === 'hooks/list') out({ id: message.id, result: { data: [{ cwd: process.cwd(), errors: [], warnings: [], hooks: [] }] } }), process.stdout.write('\\n')
    else if (message.method !== 'initialized') process.exit(93)
  })
} else if (JSON.stringify(args) === JSON.stringify(['plugin', 'marketplace', 'list', '--json'])) {
  out({ marketplaces: JSON.parse(readFileSync(env.REGISTRATION, 'utf8')) })
} else if (args.length === 5 && args.slice(0, 3).join(' ') === 'plugin marketplace add' && args[4] === '--json') {
  writeFileSync(env.REGISTRATION, JSON.stringify([{ name: 'example-market', root: args[3] }]))
  out({})
} else if (args.length === 4 && args[0] === 'plugin' && args[1] === 'add' && args[3] === '--json') {
  if (env.ADD_FAILURE) { process.stderr.write('fixture install failed'); process.exit(23) }
  const [name, marketplace] = args[2].split('@')
  if (marketplace !== 'example-market' || !['alpha', 'beta'].includes(name)) process.exit(91)
  const target = join(home, 'plugins', 'cache', marketplace, name, '1.0.0')
  // Mirror cache replacement, including removing the script that launched us.
  if (!target.startsWith(resolve(home) + sep)) process.exit(92)
  if (existsSync(target)) rmSync(target, { recursive: true, force: true })
  cpSync(join(env.MARKETPLACE_ROOT, 'components', name), target, { recursive: true })
  out({ installedPath: env.BAD_RESULT ? join(home, 'missing') : target })
} else { process.stderr.write('unexpected command: ' + JSON.stringify(args)); process.exit(91) }
`)
  const invoke = (args = ['--plugin', 'alpha'], extraEnv = {}, withHome = true) => spawnSync(process.execPath, [
    helper, '--repo', repo, ...args, ...(withHome ? ['--target-home', home] : []),
  ], {
    cwd: root,
    encoding: 'utf8',
    env: { ...process.env, USERPROFILE: userProfile, HOME: userProfile, CODEX_BIN: fakeCodex, COMMAND_LOG: log, REGISTRATION: registration, MARKETPLACE_ROOT: repo, ...extraEnv },
  })
  const calls = () => existsSync(log) ? readFileSync(log, 'utf8').trim().split('\n').map(JSON.parse) : []
  return { root, repo, home, userProfile, log, registration, selected, helper, fakeCodex, sibling, entries, marketplacePath, invoke, calls }
}

function prepareFixture(f, { fail = false } = {}) {
  writeJson(join(f.repo, 'package.json'), { scripts: { 'plugin:prepare-local': 'node prepare.mjs' } })
  writeFileSync(join(f.repo, 'input.txt'), 'fresh compiled source')
  writeFileSync(join(f.repo, 'prepare.mjs'), `
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
writeFileSync('prepared.txt', 'ran')
if (${fail}) process.exit(17)
mkdirSync('components/alpha/.codex-plugin', { recursive: true })
writeFileSync('components/alpha/.codex-plugin/plugin.json', JSON.stringify({ name: 'alpha', version: '1.0.0' }))
writeFileSync('components/alpha/content.txt', readFileSync('input.txt'))
`)
}

function writeAgentRole(root, name) {
  mkdirSync(join(root, 'agents'), { recursive: true })
  writeFileSync(join(root, 'agents', `${name}.toml`), [
    `description = "${name} fixture role"`,
    'developer_instructions = "Perform the assigned fixture work."',
    'model = "gpt-6-luna"',
    'model_reasoning_effort = "medium"',
  ].join('\n'))
}

function configFileLine(path) {
  const tomlValue = path.replaceAll('\\', '\\\\').replaceAll('"', '\\"')
  return `config_file = "${tomlValue}"`
}

function configFilePattern(path) {
  const tomlValue = configFileLine(path)
  const literal = tomlValue.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')
  return new RegExp(literal, 'u')
}

function oplFixture(t) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'refresh-opl-agent-test-')))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const repo = join(root, 'marketplace')
  const source = join(repo, 'plugins', 'opl')
  const home = join(root, 'consumer home')
  const versionOne = join(home, 'plugins', 'cache', 'example-market', 'opl', '0.2.0')
  const helper = join(versionOne, 'skills', 'refresh-local-plugins', 'scripts', 'install-local.mjs')
  const config = join(home, 'config.toml')
  const registration = join(root, 'marketplaces.json')
  const log = join(root, 'commands.jsonl')
  const marketplacePath = join(repo, '.agents', 'plugins', 'marketplace.json')
  mkdirSync(home, { recursive: true })
  mkdirSync(join(source, 'scripts'), { recursive: true })
  cpSync(scripts, dirname(helper), { recursive: true })
  cpSync(scripts, dirname(helper.replace(versionOne, source)), { recursive: true })
  cpSync(join(oplScripts, 'codex-config-check.py'), join(source, 'scripts', 'codex-config-check.py'))
  cpSync(join(oplScripts, '..', 'skills', 'configure-harness', 'scripts', 'application.py'), join(source, 'skills', 'configure-harness', 'scripts', 'application.py'))
  writeFileSync(join(source, 'config.defaults.toml'), [
    '[features]',
    'hooks = true',
    'plugins = true',
    'multi_agent = true',
    '',
    '[agents]',
    'enabled = true',
    'default_subagent_model = "gpt-6-luna"',
    'default_subagent_reasoning_effort = "medium"',
    '',
  ].join('\n'))
  writeJson(join(source, '.codex-plugin', 'plugin.json'), { name: 'opl', version: '0.2.0' })
  writeAgentRole(source, 'task')
  writeAgentRole(source, 'scout')
  writeJson(marketplacePath, {
    name: 'example-market',
    plugins: [{ name: 'opl', source: { source: 'local', path: './plugins/opl' } }],
  })
  writeFileSync(config, [
    'model = "keep-me"',
    '# opl:ignore-config-check version=0.2.0',
    '',
    '[agents.personal]',
    'config_file = "personal.toml"',
    '',
    '[agents.opl-task]',
    'config_file = "stale-task.toml"',
    '',
    '[agents.opl-retired]',
    'config_file = "retired.toml"',
    '',
  ].join('\n'))
  writeJson(registration, [])
  const fakeCodex = join(root, 'codex.mjs')
  writeFileSync(fakeCodex, `
import { appendFileSync, cpSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import readline from 'node:readline'
const args = process.argv.slice(2)
const env = process.env
appendFileSync(env.COMMAND_LOG, JSON.stringify({ args, home: env.CODEX_HOME }) + '\\n')
const out = (value) => process.stdout.write(JSON.stringify(value))
if (JSON.stringify(args) === JSON.stringify(['app-server', '--stdio'])) {
  readline.createInterface({ input: process.stdin }).on('line', (line) => {
    const message = JSON.parse(line)
    if (message.method === 'initialize') out({ id: message.id, result: {} }), process.stdout.write('\\n')
    else if (message.method === 'hooks/list') out({ id: message.id, result: { data: [{ cwd: process.cwd(), errors: [], warnings: [], hooks: [] }] } }), process.stdout.write('\\n')
    else if (message.method !== 'initialized') process.exit(93)
  })
} else if (JSON.stringify(args) === JSON.stringify(['plugin', 'marketplace', 'list', '--json'])) {
  out({ marketplaces: JSON.parse(readFileSync(env.REGISTRATION, 'utf8')) })
} else if (args.length === 5 && args.slice(0, 3).join(' ') === 'plugin marketplace add' && args[4] === '--json') {
  writeFileSync(env.REGISTRATION, JSON.stringify([{ name: 'example-market', root: args[3] }]))
  out({})
} else if (JSON.stringify(args.slice(0, 2)) === JSON.stringify(['plugin', 'add']) && args[3] === '--json') {
  if (args[2] !== 'opl@example-market') process.exit(91)
  const source = join(env.MARKETPLACE_ROOT, 'plugins', 'opl')
  const version = JSON.parse(readFileSync(join(source, '.codex-plugin', 'plugin.json'), 'utf8')).version
  const target = join(env.CODEX_HOME, 'plugins', 'cache', 'example-market', 'opl', version)
  if (existsSync(target)) rmSync(target, { recursive: true, force: true })
  cpSync(source, target, { recursive: true })
  out({ installedPath: target })
} else {
  process.stderr.write('unexpected command: ' + JSON.stringify(args))
  process.exit(91)
}
`)
  const invoke = () => spawnSync(process.execPath, [helper, '--repo', repo, '--plugin', 'opl', '--target-home', home], {
    cwd: root,
    encoding: 'utf8',
    env: { ...process.env, CODEX_BIN: fakeCodex, COMMAND_LOG: log, REGISTRATION: registration, MARKETPLACE_ROOT: repo },
  })
  const rolePath = (version, name) => join(home, 'plugins', 'cache', 'example-market', 'opl', version, 'agents', `${name}.toml`)
  return { source, home, config, helper, invoke, rolePath }
}

test('an explicit OPL refresh dynamically reconciles added, removed, and rebound installed agent roles', (t) => {
  const f = oplFixture(t)
  let result = f.invoke()
  assert.equal(result.status, 0, result.stderr)
  let contents = readFileSync(f.config, 'utf8')
  assert.match(contents, /model = "keep-me"/u)
  assert.match(contents, /\[agents\.personal\]/u)
  assert.match(contents, configFilePattern(f.rolePath('0.2.0', 'task')))
  assert.match(contents, configFilePattern(f.rolePath('0.2.0', 'scout')))
  assert.doesNotMatch(contents, /\[agents\.opl-retired\]/u)

  writeFileSync(f.config, contents.replace(configFileLine(f.rolePath('0.2.0', 'task')), 'config_file = "manually-stale.toml"'))
  result = f.invoke()
  assert.equal(result.status, 0, result.stderr)
  contents = readFileSync(f.config, 'utf8')
  assert.match(contents, configFilePattern(f.rolePath('0.2.0', 'task')))

  rmSync(join(f.source, 'agents', 'scout.toml'))
  writeAgentRole(f.source, 'review')
  writeJson(join(f.source, '.codex-plugin', 'plugin.json'), { name: 'opl', version: '0.2.1' })
  result = f.invoke()
  assert.equal(result.status, 0, result.stderr)
  contents = readFileSync(f.config, 'utf8')
  assert.match(contents, configFilePattern(f.rolePath('0.2.1', 'task')))
  assert.match(contents, configFilePattern(f.rolePath('0.2.1', 'review')))
  assert.doesNotMatch(contents, /\[agents\.opl-scout\]/u)
})

test('modified selection prepares source before comparing an unchanged old bundle', (t) => {
  const f = fixture(t)
  cpSync(join(f.repo, 'components', 'beta'), join(f.home, 'plugins', 'cache', 'example-market', 'beta', '1.0.0'), { recursive: true })
  // The prepared bundle and installed copy are identical before the source edit.
  cpSync(join(f.repo, 'components', 'alpha'), f.selected, { recursive: true })
  cpSync(dirname(f.helper), join(f.repo, 'components', 'alpha', 'skills', 'refresh-local-plugins', 'scripts'), { recursive: true })
  prepareFixture(f)
  const result = f.invoke([])
  assert.equal(result.status, 0, result.stderr)
  assert.equal(readFileSync(join(f.selected, 'content.txt'), 'utf8'), 'fresh compiled source')
  assert.deepEqual(f.calls().filter(({ args }) => args[1] === 'add').map(({ args }) => args[2]), ['alpha@example-market'])
})

test('preparation creates a missing bundle on a fresh checkout', (t) => {
  const f = fixture(t)
  prepareFixture(f)
  rmSync(join(f.repo, 'components', 'alpha'), { recursive: true })
  const result = f.invoke()
  assert.equal(result.status, 0, result.stderr)
  assert.equal(readFileSync(join(f.selected, 'content.txt'), 'utf8'), 'fresh compiled source')
})

test('failed preparation preserves installed bytes and performs no installation', (t) => {
  const f = fixture(t)
  prepareFixture(f, { fail: true })
  const result = f.invoke()
  assert.equal(result.status, 1)
  assert.match(result.stderr, /prepar.*failed/iu)
  assert.ok(existsSync(f.helper))
  assert.ok(f.calls().every(({ args }) => args.join(' ') === 'plugin marketplace list --json'))
})

test('preview reports required preparation without building a missing bundle', (t) => {
  const f = fixture(t)
  prepareFixture(f)
  rmSync(join(f.repo, 'components', 'alpha'), { recursive: true })
  const result = f.invoke(['--dry-run', '--plugin', 'alpha'])
  assert.equal(result.status, 0, result.stderr)
  assert.equal(JSON.parse(result.stdout).preparation.command, 'npm run plugin:prepare-local')
  assert.equal(existsSync(join(f.repo, 'prepared.txt')), false)
  assert.deepEqual(f.calls(), [])
})

test('registration conflict prevents preparation as well as installation', (t) => {
  const f = fixture(t)
  prepareFixture(f)
  writeJson(f.registration, [{ name: 'example-market', root: f.root }])
  const result = f.invoke()
  assert.equal(result.status, 1)
  assert.equal(existsSync(join(f.repo, 'prepared.txt')), false)
})

for (const [manifest, source] of [
  ['.agents/plugins/marketplace.json', { source: 'local', path: './components/alpha' }],
  ['.agents/plugins/api_marketplace.json', { source: 'local', path: './components/alpha' }],
]) {
  test(`installed helper refreshes a Codex ${manifest} marketplace and its own cache`, (t) => {
    const f = fixture(t, manifest)
    f.entries[0].source = source
    writeJson(f.marketplacePath, { name: 'example-market', plugins: f.entries })
    const result = f.invoke()
    assert.equal(result.status, 0, result.stderr)
    assert.equal(readFileSync(join(f.selected, 'content.txt'), 'utf8'), 'alpha new bytes')
    assert.equal(existsSync(f.helper), false, 'the running script was replaced successfully')
    assert.equal(readFileSync(f.sibling, 'utf8'), 'leave me alone')
    assert.equal(existsSync(join(f.home, 'plugins', 'cache', 'example-market', 'beta')), false)
    assert.deepEqual(f.calls().map(({ args }) => args), [
      ['plugin', 'marketplace', 'list', '--json'],
      ['plugin', 'marketplace', 'add', f.repo, '--json'],
      ['plugin', 'add', 'alpha@example-market', '--json'],
      ['app-server', '--stdio'],
    ])
    assert.ok(f.calls().every(({ home, cwd }) => home === f.home && cwd === f.repo))
    assert.match(result.stdout, /installed and enabled/u)
  })
}

test('an existing matching registration and repeated plugin selections refresh only those plugins', (t) => {
  const f = fixture(t)
  writeJson(f.registration, [{ name: 'example-market', root: f.repo }])
  const result = f.invoke(['--plugin', 'alpha', '--plugin', 'beta'])
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(f.calls().map(({ args }) => args), [
    ['plugin', 'marketplace', 'list', '--json'],
    ['plugin', 'add', 'alpha@example-market', '--json'],
    ['app-server', '--stdio'],
    ['plugin', 'add', 'beta@example-market', '--json'],
    ['app-server', '--stdio'],
  ])
  assert.equal(readFileSync(join(f.home, 'plugins', 'cache', 'example-market', 'beta', '1.0.0', 'content.txt'), 'utf8'), 'beta new bytes')
})

test('explicit all refreshes every marketplace plugin', (t) => {
  const f = fixture(t)
  const result = f.invoke(['--plugin', 'all'])
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(f.calls().filter(({ args }) => args[1] === 'add').map(({ args }) => args[2]), ['alpha@example-market', 'beta@example-market'])
})

test('a different checkout registered under the same name stops before any mutation', (t) => {
  const f = fixture(t)
  writeJson(f.registration, [{ name: 'example-market', root: f.root }])
  const result = f.invoke()
  assert.equal(result.status, 1)
  assert.match(result.stderr, /registered at/u)
  assert.deepEqual(f.calls().map(({ args }) => args), [['plugin', 'marketplace', 'list', '--json']])
  assert.equal(existsSync(f.helper), true)
})

test('counterpart refresh uses its own registered checkout', (t) => {
  const f = fixture(t)
  const peer = join(f.root, 'peer checkout')
  cpSync(f.repo, peer, { recursive: true })
  prepareFixture({ ...f, repo: peer })
  writeFileSync(join(peer, 'input.txt'), 'peer new bytes')
  writeJson(f.registration, [{ name: 'example-market', root: peer }])
  const result = f.invoke(['--plugin', 'alpha', '--local-only', '--registered-source'], { MARKETPLACE_ROOT: peer }, false)
  assert.equal(result.status, 0, result.stderr)
  assert.equal(readFileSync(join(f.userProfile, '.codex', 'plugins', 'cache', 'example-market', 'alpha', '1.0.0', 'content.txt'), 'utf8'), 'peer new bytes')
  assert.equal(f.calls()[0].cwd, f.repo)
  assert.equal(f.calls()[1].cwd, peer)
  assert.equal(existsSync(join(f.repo, 'prepared.txt')), false)
  assert.equal(readFileSync(join(peer, 'prepared.txt'), 'utf8'), 'ran')
})

test('dry run validates and prints sources without invoking Codex or creating the target home', (t) => {
  const f = fixture(t)
  const absentHome = join(f.root, 'preview only')
  const result = f.invoke(['--plugin', 'alpha', '--target-home', absentHome, '--dry-run'], {}, false)
  assert.equal(result.status, 0, result.stderr)
  const plan = JSON.parse(result.stdout)
  assert.equal(plan.home, absentHome)
  assert.deepEqual(plan.plugins, [{ name: 'alpha', pluginId: 'alpha@example-market', source: join(f.repo, 'components', 'alpha') }])
  assert.deepEqual(f.calls(), [])
  assert.equal(existsSync(absentHome), false)
})

test('the helper runs when reached through a skill directory junction', (t) => {
  const f = fixture(t)
  const alias = join(f.root, 'linked skill scripts')
  symlinkSync(dirname(f.helper), alias, process.platform === 'win32' ? 'junction' : 'dir')
  const result = spawnSync(process.execPath, [join(alias, 'install-local.mjs'), '--help'], { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /Usage: node install-local.mjs/u)
  assert.deepEqual(f.calls(), [])
})

for (const path of ['components/alpha', './components/../components/alpha']) {
  test(`dry run rejects Codex-incompatible local path ${path}`, (t) => {
    const f = fixture(t)
    f.entries[0].source.path = path
    writeJson(f.marketplacePath, { name: 'example-market', plugins: f.entries })
    const result = f.invoke(['--plugin', 'all', '--dry-run'])
    assert.equal(result.status, 1, result.stdout)
    assert.match(result.stderr, /local source path/u)
    assert.deepEqual(f.calls(), [])
  })
}

for (const [label, args, withHome, expected] of [
  ['relative home', ['--plugin', 'alpha', '--target-home', 'relative'], false, /absolute/u],
  ['unknown plugin', ['--plugin', 'missing'], true, /Unknown plugin/u],
  ['all combined with a name', ['--plugin', 'all', '--plugin', 'alpha'], true, /must be used alone/u],
]) {
  test(`${label} stops before any Codex command`, (t) => {
    const f = fixture(t)
    const result = f.invoke(args, {}, withHome)
    assert.equal(result.status, 1)
    assert.match(result.stderr, expected)
    assert.deepEqual(f.calls(), [])
  })
}

test('no plugin selects every source that differs from its installed copy', (t) => {
  const f = fixture(t)
  const betaSource = join(f.repo, 'components', 'beta')
  const betaInstalled = join(f.home, 'plugins', 'cache', 'example-market', 'beta', '1.0.0')
  cpSync(betaSource, betaInstalled, { recursive: true })
  const result = f.invoke(['--dry-run'])
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout).plugins.map(({ name }) => name), ['alpha'])
  assert.deepEqual(f.calls(), [])
})

test('modified selection does not install a plugin absent from that home', (t) => {
  const f = fixture(t)
  const result = f.invoke(['--dry-run'])
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout).plugins.map(({ name }) => name), ['alpha'])
})

test('no target home uses an existing user-level Codex home', (t) => {
  const f = fixture(t)
  const result = f.invoke(['--plugin', 'alpha', '--dry-run', '--local-only'], {}, false)
  assert.equal(result.status, 0, result.stderr)
  assert.equal(JSON.parse(result.stdout).home, join(f.userProfile, '.codex'))
  assert.deepEqual(f.calls(), [])
})

test('unchanged plugins require no marketplace registration or install', (t) => {
  const f = fixture(t)
  for (const name of ['alpha', 'beta']) {
    const target = join(f.home, 'plugins', 'cache', 'example-market', name, '1.0.0')
    rmSync(target, { recursive: true, force: true })
    cpSync(join(f.repo, 'components', name), target, { recursive: true })
  }
  const result = spawnSync(process.execPath, [join(scripts, 'install-local.mjs'), '--repo', f.repo, '--target-home', f.home], {
    cwd: f.root,
    encoding: 'utf8',
    env: { ...process.env, USERPROFILE: f.userProfile, HOME: f.userProfile, CODEX_BIN: f.fakeCodex, COMMAND_LOG: f.log, REGISTRATION: f.registration, MARKETPLACE_ROOT: f.repo },
  })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /No modified plugins/u)
  assert.deepEqual(f.calls(), [])
})

test('an absent user-level Codex home stops before mutation', (t) => {
  const f = fixture(t)
  const result = f.invoke(['--plugin', 'alpha', '--local-only'], { USERPROFILE: join(f.root, 'absent user'), HOME: join(f.root, 'absent user') }, false)
  assert.equal(result.status, 1)
  assert.match(result.stderr, /User-level Codex home does not exist/u)
  assert.deepEqual(f.calls(), [])
})

test('one helper invocation routes Windows to WSL with translated paths and local-only recursion', () => {
  const invocation = counterpartInvocation({
    platform: 'win32', script: 'C:\\skill\\install-local.mjs', repo: 'C:\\source',
    plugins: ['alpha', 'beta'], dryRun: true,
    translate: (path) => path.replace('C:\\', '/mnt/c/').replaceAll('\\', '/'),
  })
  assert.deepEqual(invocation, {
    executable: 'wsl.exe',
    args: ['--exec', 'bash', '-lc', "node '/mnt/c/skill/install-local.mjs' '--repo' '/mnt/c/source' '--plugin' 'alpha' '--plugin' 'beta' '--dry-run' '--local-only' '--registered-source'"],
  })
})

test('one helper invocation routes WSL to Windows with safe quoted paths', () => {
  const invocation = counterpartInvocation({
    platform: 'linux', script: "/mnt/c/skill's helper/install-local.mjs", repo: '/mnt/c/source',
    plugins: ['alpha'], translate: (path) => path.replace('/mnt/c/', 'C:\\').replaceAll('/', '\\'),
  })
  assert.equal(invocation.executable, 'powershell.exe')
  assert.deepEqual(invocation.args.slice(0, 3), ['-NoProfile', '-NonInteractive', '-EncodedCommand'])
  const decoded = Buffer.from(invocation.args[3], 'base64').toString('utf16le')
  assert.equal(decoded, "& node 'C:\\skill''s helper\\install-local.mjs' '--repo' 'C:\\source' '--plugin' 'alpha' '--local-only' '--registered-source'; exit $LASTEXITCODE")
})

test('all preflights every selected source before installing any plugin', (t) => {
  const f = fixture(t)
  f.entries[1].source = { source: 'url', url: 'https://example.com/plugin.git' }
  writeJson(f.marketplacePath, { name: 'example-market', plugins: f.entries })
  const result = f.invoke(['--plugin', 'all'])
  assert.equal(result.status, 1)
  assert.match(result.stderr, /beta: refresh requires a relative local plugin source/u)
  assert.deepEqual(f.calls(), [])
})

test('a source outside the checkout is rejected before Codex runs', (t) => {
  const f = fixture(t)
  f.entries[0].source.path = '..'
  writeJson(f.marketplacePath, { name: 'example-market', plugins: f.entries })
  const result = f.invoke()
  assert.equal(result.status, 1)
  assert.match(result.stderr, /local source path/u)
  assert.deepEqual(f.calls(), [])
})

for (const aliased of [false, true]) {
  test(`a destination inside plugin source is rejected${aliased ? ' through an existing junction parent' : ''}`, (t) => {
    const f = fixture(t)
    const source = join(f.repo, 'components', 'alpha')
    const parent = aliased ? join(f.root, 'source alias') : source
    if (aliased) symlinkSync(source, parent, process.platform === 'win32' ? 'junction' : 'dir')
    const destination = join(parent, 'new home')
    const result = f.invoke(['--plugin', 'alpha', '--target-home', destination], {}, false)
    assert.equal(result.status, 1, result.stdout)
    assert.match(result.stderr, /Codex home.*inside.*plugin source/u)
    assert.deepEqual(f.calls(), [])
    assert.equal(existsSync(destination), false)
  })
}

test('a relocated cache inside plugin source is rejected during preflight', (t) => {
  const f = fixture(t)
  const home = join(f.root, 'relocated-cache-home')
  mkdirSync(join(home, 'plugins'), { recursive: true })
  symlinkSync(join(f.repo, 'components', 'alpha'), join(home, 'plugins', 'cache'), process.platform === 'win32' ? 'junction' : 'dir')
  const result = f.invoke(['--plugin', 'alpha', '--target-home', home, '--dry-run'], {}, false)
  assert.equal(result.status, 1, result.stdout)
  assert.match(result.stderr, /cache.*overlap.*plugin source/u)
  assert.deepEqual(f.calls(), [])
})

test('a failed install reports the failing plugin and stops before later plugins', (t) => {
  const f = fixture(t)
  const result = f.invoke(['--plugin', 'all'], { ADD_FAILURE: '1' })
  assert.equal(result.status, 1)
  assert.match(result.stderr, /alpha@example-market.*fixture install failed/u)
  assert.equal(f.calls().filter(({ args }) => args[1] === 'add').length, 1)
  assert.equal(existsSync(f.helper), true)
})

test('an unusable install result is reported as a failure', (t) => {
  const f = fixture(t)
  const result = f.invoke(['--plugin', 'alpha'], { BAD_RESULT: '1' })
  assert.equal(result.status, 1)
  assert.match(result.stderr, /usable installedPath/u)
})

test('a plugin declaring hooks must have those hooks discovered and trusted', (t) => {
  const f = fixture(t)
  const source = join(f.repo, 'components', 'alpha')
  const manifestPath = join(source, '.codex-plugin', 'plugin.json')
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  manifest.hooks = './hooks/hooks.json'
  writeJson(manifestPath, manifest)
  writeJson(join(source, 'hooks', 'hooks.json'), { hooks: { SessionStart: [{ hooks: [{ type: 'command', command: 'echo ready' }] }] } })
  const result = f.invoke()
  assert.equal(result.status, 1, result.stdout)
  assert.match(result.stderr, /declares hooks but Codex discovered none/u)
})

test('failed automatic hook trust still refreshes later plugins and names the affected home', (t) => {
  const f = fixture(t)
  const source = join(f.repo, 'components', 'alpha')
  const manifestPath = join(source, '.codex-plugin', 'plugin.json')
  writeJson(manifestPath, { ...JSON.parse(readFileSync(manifestPath, 'utf8')), hooks: './hooks/hooks.json' })
  writeJson(join(source, 'hooks', 'hooks.json'), { hooks: { SessionStart: [{ hooks: [{ type: 'command', command: 'echo ready' }] }] } })
  const result = f.invoke(['--plugin', 'all'])
  assert.equal(result.status, 1)
  assert.match(result.stderr, /Automatic hook trust failed for/u)
  assert.match(result.stderr, /alpha@example-market/u)
  assert.equal(existsSync(join(f.home, 'plugins', 'cache', 'example-market', 'beta', '1.0.0', 'content.txt')), true)
})
