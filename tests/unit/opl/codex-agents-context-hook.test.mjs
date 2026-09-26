import test from 'node:test'
import assert from 'node:assert/strict'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { pythonBin } from '../../../tools/runtime.mjs'

const plugin = fileURLToPath(new URL('../../../plugins/opl/', import.meta.url))
const text = (n) => `<!-- opl-instructions-version: ${n} -->\n\nKeep café and 🚀.\n`
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'OPL notice é '))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const home = join(root, 'home')
  const installed = join(root, 'installed')
  mkdirSync(home)
  mkdirSync(join(installed, 'scripts'), { recursive: true })
  cpSync(join(plugin, 'scripts/codex-agents-context-hook.py'), join(installed, 'scripts/codex-agents-context-hook.py'))
  cpSync(join(plugin, 'skills/update-instructions/scripts'), join(installed, 'skills/update-instructions/scripts'), { recursive: true })
  writeFileSync(join(installed, 'AGENTS.md'), text(3))
  const target = join(home, 'AGENTS.md')
  const env = { ...process.env, CODEX_HOME: home, PLUGIN_ROOT: installed }
  const run = (payload = {}, customEnv = env) => spawnSync(pythonBin(), ['-B', '-X', 'utf8', join(installed, 'scripts/codex-agents-context-hook.py')], { env: customEnv, input: JSON.stringify(payload), encoding: 'utf8', windowsHide: true })
  return { root, home, installed, target, env, run }
}

for (const source of ['startup', 'resume', 'clear', 'compact']) {
  test(`local update notice for ${source} preserves user instructions`, (t) => {
    const f = fixture(t)
    const original = '\ufeff' + text(1).replaceAll('\n', '\r\n')
    writeFileSync(f.target, original)
    const result = f.run({ hook_event_name: 'SessionStart', source })
    assert.equal(result.status, 0, result.stderr)
    const output = JSON.parse(result.stdout)
    assert.match(output.systemMessage, /version 3.*baseline: 1/u)
    assert.match(output.hookSpecificOutput.additionalContext, /\$opl:update-instructions/u)
    assert.ok(!output.hookSpecificOutput.additionalContext.includes('Keep café'))
    assert.equal(readFileSync(f.target, 'utf8'), original)
  })
}

test('matching version stays silent and newer version does not suggest downgrade', (t) => {
  const f = fixture(t)
  writeFileSync(f.target, text(3))
  assert.deepEqual(JSON.parse(f.run().stdout), {})
  writeFileSync(f.target, text(4))
  assert.match(JSON.parse(f.run().stdout).systemMessage, /newer.*rather than downgrade/u)
})

test('missing and malformed markers are actionable; override takes precedence', (t) => {
  const f = fixture(t)
  assert.match(JSON.parse(f.run().stdout).systemMessage, /not set up/u)
  writeFileSync(f.target, text(1) + text(2))
  assert.match(JSON.parse(f.run().stdout).systemMessage, /invalid/u)
  writeFileSync(join(f.home, 'AGENTS.override.md'), text(3))
  assert.deepEqual(JSON.parse(f.run().stdout), {})
})

test('installed helper resolves without PLUGIN_ROOT and rejects invalid stock', (t) => {
  const f = fixture(t)
  const env = { ...f.env }
  delete env.PLUGIN_ROOT
  assert.equal(f.run({}, env).status, 0)
  writeFileSync(join(f.installed, 'AGENTS.md'), 'No version')
  assert.notEqual(f.run().status, 0)
  assert.notEqual(f.run({ hook_event_name: 'SubagentStart' }).status, 0)
})

test('manifest keeps lifecycle notices and removes subagent stock injection', () => {
  const hooks = JSON.parse(readFileSync(join(plugin, 'hooks/hooks.json'), 'utf8')).hooks
  const group = hooks.SessionStart.find((g) => g.hooks.some((h) => h.command.includes('codex-agents-context-hook')))
  assert.equal(group.matcher, 'startup|resume|clear|compact')
  assert.equal(group.hooks[0].additionalContextLimit, 2048)
  const configCheck = hooks.SessionStart.find((g) => g.hooks.some((h) => h.command.includes('codex-config-check.py')))
  assert.equal(configCheck.matcher, 'startup|resume|clear|compact')
  assert.match(configCheck.hooks[0].commandWindows, /codex-config-check\.py" hook$/u)
  assert.ok(!hooks.SubagentStart.some((g) => g.hooks.some((h) => h.command.includes('codex-agents-context-hook'))))
})
