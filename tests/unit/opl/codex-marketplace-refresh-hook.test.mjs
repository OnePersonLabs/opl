import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { pythonBin } from '../../../tools/runtime.mjs'

const pluginRoot = fileURLToPath(new URL('../../../plugins/opl/', import.meta.url))
const hookPath = join(pluginRoot, 'scripts', 'codex-marketplace-refresh-hook.py')

function fixture(t, { marketplace = true, dottedPlugins = false } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'opl-marketplace-refresh-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const repo = join(root, 'source checkout')
  mkdirSync(repo)
  const init = spawnSync('git', ['init', '-q', repo], { encoding: 'utf8', windowsHide: true })
  assert.equal(init.status, 0, init.stderr)
  if (marketplace) {
    const plugins = join(repo, '.agents', 'plugins')
    mkdirSync(plugins, { recursive: true })
    writeFileSync(join(plugins, 'marketplace.json'), '{}')
  }
  if (dottedPlugins) {
    const plugins = join(repo, '.agents', '.plugins')
    mkdirSync(plugins, { recursive: true })
    writeFileSync(join(plugins, 'marketplace.json'), '{}')
  }
  return { root, repo }
}

function runHook({ repo }, command, extra = {}) {
  return spawnSync(pythonBin(), ['-B', '-X', 'utf8', hookPath], {
    input: JSON.stringify({
      hook_event_name: 'PostToolUse',
      tool_name: 'Bash',
      cwd: repo,
      tool_input: { command },
      tool_response: '',
      ...extra,
    }),
    encoding: 'utf8',
    windowsHide: true,
  })
}

function context(result) {
  assert.equal(result.status, 0, result.stderr)
  if (!result.stdout) return null
  const output = JSON.parse(result.stdout)
  assert.deepEqual(Object.keys(output), ['hookSpecificOutput'])
  assert.equal(output.hookSpecificOutput.hookEventName, 'PostToolUse')
  return output.hookSpecificOutput.additionalContext
}

test('push and pull in a marketplace checkout remind the agent conditionally', (t) => {
  const state = fixture(t)
  for (const command of ['git push origin main', 'git pull --ff-only', 'git.exe push']) {
    const message = context(runHook(state, command))
    assert.match(message, /if (?:the )?git (?:push|pull) succeeded/iu)
    assert.match(message, /\$opl:refresh-local-plugins/u)
  }
})

test('a subdirectory and explicit git -C target resolve to the marketplace root', (t) => {
  const state = fixture(t)
  const nested = join(state.repo, 'nested directory')
  mkdirSync(nested)
  assert.ok(context(runHook(state, 'git pull', { tool_input: { command: 'git pull', workdir: nested } })))
  assert.ok(context(runHook(state, 'git -C "nested directory" push')))
})

test('only the canonical marketplace manifest triggers the reminder', (t) => {
  const state = fixture(t, { marketplace: false, dottedPlugins: true })
  assert.equal(context(runHook(state, 'git push')), null)
  mkdirSync(join(state.repo, '.agents', 'plugins'), { recursive: true })
  writeFileSync(join(state.repo, '.agents', 'plugins', 'marketplace.json'), '{}')
  assert.ok(context(runHook(state, 'git pull')))
})

test('unrelated commands and Git operations outside the marketplace stay silent', (t) => {
  const state = fixture(t)
  const other = join(state.root, 'other repo')
  mkdirSync(other)
  const init = spawnSync('git', ['init', '-q', other], { encoding: 'utf8', windowsHide: true })
  assert.equal(init.status, 0, init.stderr)
  for (const command of ['git fetch', 'echo git push', 'git status', 'cd elsewhere && git pull']) {
    assert.equal(context(runHook(state, command)), null, command)
  }
  assert.equal(context(runHook(state, `git -C "${other}" push`)), null)
})

test('the reminder stays conditional even when Git output reports failure', (t) => {
  const state = fixture(t)
  const message = context(runHook(state, 'git pull', { tool_response: 'fatal: remote branch not found' }))
  assert.match(message, /if (?:the )?git pull succeeded/iu)
})

test('manifest registers the dedicated hook for native Windows and POSIX sessions', () => {
  const manifest = JSON.parse(readFileSync(join(pluginRoot, 'hooks', 'hooks.json'), 'utf8'))
  const group = manifest.hooks.PostToolUse.find((entry) => entry.matcher === 'Bash')
  assert.ok(group)
  const handler = group.hooks.find((entry) => entry.command.includes('codex-marketplace-refresh-hook.py'))
  assert.ok(handler)
  assert.match(handler.command, /^python3 -B -X utf8 /u)
  assert.match(handler.commandWindows, /^python -B -X utf8 /u)
  assert.equal(handler.timeout, 20)
})
