import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { ensurePluginHookTrust } from '../../../plugins/opl/skills/refresh-local-plugins/scripts/codex-hooks.mjs'

function fixture(t, { mode = 'normal', trustStatus = 'untrusted', selected = true } = {}) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "Codex hook's test-")))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const home = join(root, 'isolated home')
  const repo = join(root, 'source checkout')
  const installedPath = join(home, 'plugins', 'cache', 'market', 'demo', '1.0.0')
  mkdirSync(installedPath, { recursive: true })
  mkdirSync(repo)
  const sourcePath = join(installedPath, 'hooks.json')
  writeFileSync(sourcePath, '{}')
  const config = join(home, 'config.toml')
  writeFileSync(config, '[plugins."demo@market"]\nenabled = true\n')
  const statePath = join(root, 'native-state.json')
  const hook = {
    key: 'demo@market:hooks.json:pre_tool_use:0:0',
    pluginId: 'demo@market',
    currentHash: 'discovered-hash-1',
    trustStatus,
    enabled: false,
    sourcePath,
    handlerType: 'command',
    command: 'echo selected hook',
    eventName: 'preToolUse',
  }
  const state = {
    [hook.key]: { enabled: false, trusted_hash: 'previous-hash' },
    'other@market:hooks.json:pre_tool_use:0:0': { enabled: true, trusted_hash: 'unrelated-hash' },
  }
  writeFileSync(statePath, JSON.stringify(state))
  const spec = join(root, 'fixture.json')
  writeFileSync(spec, JSON.stringify({ mode, selected, hook, config, repo, home, statePath }))
  const log = join(root, 'rpc.jsonl')
  const fakeCodex = join(root, 'codex.mjs')
  writeFileSync(fakeCodex, `
import assert from 'node:assert/strict'
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs'
import readline from 'node:readline'
const spec = JSON.parse(readFileSync(process.env.HOOK_FIXTURE, 'utf8'))
assert.deepEqual(process.argv.slice(2), ['app-server', '--stdio'])
assert.equal(process.cwd(), spec.repo)
assert.equal(process.env.CODEX_HOME, spec.home)
let approved = false
const lines = readline.createInterface({ input: process.stdin })
const result = (id, value) => process.stdout.write(JSON.stringify({ id, result: value }) + '\\n')
lines.on('line', (line) => {
  const request = JSON.parse(line)
  appendFileSync(process.env.HOOK_RPC_LOG, line + '\\n')
  if (spec.mode === 'early-exit') { process.stderr.write('fixture process stopped'); process.exit(9) }
  if (spec.mode === 'invalid-json') { process.stdout.write('broken JSON\\n'); return }
  if (request.method === 'initialized') { assert.equal(request.id, undefined); return }
  if (spec.mode === 'api-error-' + request.method) {
    process.stdout.write(JSON.stringify({ id: request.id, error: { code: -32001, message: 'fixture RPC failure' } }) + '\\n')
    return
  }
  if (request.method === 'initialize') { result(request.id, { userAgent: 'fixture' }); return }
  if (request.method === 'hooks/list') {
    assert.deepEqual(request.params, { cwds: [spec.repo] })
    if (spec.mode === 'malformed-shape') { result(request.id, { data: [{ hooks: [] }] }); return }
    const hook = { ...spec.hook }
    if (approved && spec.mode !== 'still-untrusted') hook.trustStatus = 'trusted'
    if (approved && spec.mode === 'changed-hash') hook.currentHash = 'changed-after-approval'
    if (approved && spec.mode === 'changed-enabled') hook.enabled = true
    if (spec.mode === 'wrong-source') hook.sourcePath = spec.config
    if (spec.mode === 'missing-hash') delete hook.currentHash
    result(request.id, { data: [{ cwd: spec.repo, hooks: [
      ...(spec.selected ? [hook] : []),
      { key: 'other@market:hooks.json:pre_tool_use:0:0', pluginId: 'other@market', currentHash: 'other-new-hash', trustStatus: 'untrusted', enabled: true, sourcePath: spec.config },
    ], warnings: [], errors: spec.mode === 'workspace-error' ? [{ path: spec.repo, message: 'fixture config is invalid' }] : [] }] })
    return
  }
  if (request.method === 'config/batchWrite') {
    assert.equal(request.params.filePath, spec.config)
    assert.equal(request.params.reloadUserConfig, true)
    assert.deepEqual(request.params.edits, [{ keyPath: 'hooks.state', value: {
      [spec.hook.key]: { trusted_hash: spec.hook.currentHash },
    }, mergeStrategy: 'upsert' }])
    const state = JSON.parse(readFileSync(spec.statePath, 'utf8'))
    for (const [key, value] of Object.entries(request.params.edits[0].value)) state[key] = { ...state[key], ...value }
    writeFileSync(spec.statePath, JSON.stringify(state))
    approved = true
    result(request.id, { status: 'ok', version: 'after-write', filePath: spec.mode === 'wrong-config' ? spec.hook.sourcePath : spec.config, overriddenMetadata: null })
    return
  }
  process.stderr.write('Unexpected RPC: ' + request.method)
  process.exit(11)
})
`)
  const invoke = (options = {}) => ensurePluginHookTrust({
    repo, home, pluginId: 'demo@market', installedPath,
    env: { ...process.env, CODEX_BIN: fakeCodex, HOOK_FIXTURE: spec, HOOK_RPC_LOG: log },
    ...options,
  })
  const calls = () => existsSync(log) ? readFileSync(log, 'utf8').trim().split('\n').map(JSON.parse) : []
  return { root, home, repo, config, sourcePath, hook, state, statePath, invoke, calls }
}

test('native approval trusts only selected hashes, preserves disabled and unrelated hooks, and verifies discovery', async (t) => {
  const f = fixture(t)
  const hooks = await f.invoke({ required: true })
  assert.deepEqual(hooks, [{ ...f.hook, trustStatus: 'trusted' }])
  assert.deepEqual(JSON.parse(readFileSync(f.statePath, 'utf8')), {
    ...f.state,
    [f.hook.key]: { enabled: false, trusted_hash: 'discovered-hash-1' },
  })
  assert.deepEqual(f.calls().map((call) => call.method), ['initialize', 'initialized', 'hooks/list', 'config/batchWrite', 'hooks/list'])
})

test('already trusted hooks need no configuration write', async (t) => {
  const f = fixture(t, { trustStatus: 'trusted' })
  assert.deepEqual(await f.invoke(), [f.hook])
  assert.deepEqual(f.calls().map((call) => call.method), ['initialize', 'initialized', 'hooks/list'])
  assert.deepEqual(JSON.parse(readFileSync(f.statePath, 'utf8')), f.state)
})

test('optional discovery returns no selected hooks without approving another plugin', async (t) => {
  const f = fixture(t, { selected: false })
  assert.deepEqual(await f.invoke(), [])
  assert.equal(f.calls().some((call) => call.method === 'config/batchWrite'), false)
})

test('required hook discovery reports an installed plugin with no discovered hooks', async (t) => {
  const f = fixture(t, { selected: false })
  await assert.rejects(f.invoke({ required: true }), /demo@market: Installed plugin declares hooks but Codex discovered none/u)
})

for (const method of ['initialize', 'hooks/list', 'config/batchWrite']) {
  test(`${method} RPC errors identify the operation and abort approval`, async (t) => {
    const f = fixture(t, { mode: `api-error-${method}` })
    await assert.rejects(f.invoke(), (error) => error.message.includes(`Codex ${method} failed (-32001): fixture RPC failure`))
    assert.equal(f.calls().at(-1).method, method)
  })
}

for (const [mode, expected] of [
  ['wrong-source', /sourcePath is outside the expected installed plugin/u],
  ['missing-hash', /no usable key or currentHash/u],
  ['workspace-error', /fixture config is invalid/u],
  ['malformed-shape', /malformed workspace metadata/u],
  ['invalid-json', /returned invalid JSON/u],
  ['early-exit', /exited before hook approval completed \(9\): fixture process stopped/u],
]) {
  test(`${mode} fails without a trust write`, async (t) => {
    const f = fixture(t, { mode })
    await assert.rejects(f.invoke(), expected)
    assert.equal(f.calls().some((call) => call.method === 'config/batchWrite'), false)
  })
}

for (const mode of ['changed-hash', 'changed-enabled', 'still-untrusted']) {
  test(`${mode} after approval does not pass verification`, async (t) => {
    const f = fixture(t, { mode })
    await assert.rejects(f.invoke(), /changed or remained untrusted after approval/u)
    assert.equal(f.calls().at(-1).method, 'hooks/list')
  })
}

test('approval response must identify the authorized configuration file', async (t) => {
  const f = fixture(t, { mode: 'wrong-config' })
  await assert.rejects(f.invoke(), /did not confirm the authorized config.toml path/u)
})

test('a config symlink into another home is rejected before approving hooks', async (t) => {
  const f = fixture(t)
  const otherConfig = join(f.root, 'other-profile.toml')
  writeFileSync(otherConfig, 'enabled = false\n')
  rmSync(f.config)
  symlinkSync(otherConfig, f.config, 'file')
  await assert.rejects(f.invoke(), /config.toml resolves outside the authorized Codex home/u)
  assert.equal(readFileSync(otherConfig, 'utf8'), 'enabled = false\n')
  assert.equal(f.calls().some((call) => call.method === 'config/batchWrite'), false)
})

test('a hook source symlink outside the installed plugin is rejected before approval', async (t) => {
  const f = fixture(t)
  rmSync(f.sourcePath)
  symlinkSync(f.config, f.sourcePath, 'file')
  await assert.rejects(f.invoke(), /sourcePath is outside the expected installed plugin/u)
  assert.equal(f.calls().some((call) => call.method === 'config/batchWrite'), false)
})

test('an unavailable Codex executable reports a launch error', async (t) => {
  const f = fixture(t)
  await assert.rejects(f.invoke({ env: { ...process.env, CODEX_BIN: join(f.root, 'missing-codex.exe') } }), /app-server could not run/u)
})

test('the total approval deadline stops an unresponsive app-server', async (t) => {
  const f = fixture(t)
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const rejection = assert.rejects(f.invoke(), /hook approval timed out after 20 seconds/u)
  t.mock.timers.tick(20000)
  await rejection
})
