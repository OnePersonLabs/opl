import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../../..', import.meta.url))

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'))
}

function commandPaths(value, output = []) {
  if (Array.isArray(value)) {
    for (const item of value) commandPaths(item, output)
  } else if (value && typeof value === 'object') {
    if (typeof value.command === 'string') {
      const match = value.command.match(/\$\{PLUGIN_ROOT\}\/([^"']+)/u)
      if (match) output.push(match[1])
    }
    for (const child of Object.values(value)) commandPaths(child, output)
  }
  return output
}

for (const pluginName of ['opl']) {
  test(`${pluginName} hook commands resolve inside the plugin`, () => {
    const pluginRoot = join(repositoryRoot, 'plugins', pluginName)
    const hooks = readJson(join(pluginRoot, 'hooks', 'hooks.json'))
    const paths = commandPaths(hooks)
    assert.ok(paths.length > 0)
    for (const path of paths) {
      assert.ok(existsSync(join(pluginRoot, path)), `${pluginName}: ${path}`)
    }
  })
}

test('OPL owns the repository-independent GitHub Issues deferral provider', () => {
  const scripts = readdirSync(join(repositoryRoot, 'plugins', 'opl', 'scripts'))
  assert.ok(scripts.includes('codex-github-issues-deferral-handler.py'))
})

test('OnePersonLabs manifest exports its hooks', () => {
  const manifest = readJson(
    join(repositoryRoot, 'plugins', 'opl', '.codex-plugin', 'plugin.json'),
  )
  assert.equal(manifest.name, 'opl')
  assert.equal(manifest.hooks, './hooks/hooks.json')
})
