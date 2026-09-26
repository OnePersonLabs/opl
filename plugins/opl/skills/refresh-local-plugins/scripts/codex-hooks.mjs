import { spawn } from 'node:child_process'
import { existsSync, realpathSync } from 'node:fs'
import { isAbsolute, join, relative, sep } from 'node:path'
import process from 'node:process'
import readline from 'node:readline'
import { codexCommand } from './codex-command.mjs'

function within(root, path) {
  const remainder = relative(root, path)
  return remainder === '' || (remainder !== '..' && !remainder.startsWith(`..${sep}`) && !isAbsolute(remainder))
}

function appServer(repo, home, environment) {
  const env = { ...environment, CODEX_HOME: home }
  const [executable, ...args] = codexCommand(['app-server', '--stdio'], { env })
  const child = spawn(executable, args, { cwd: repo, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  const lines = readline.createInterface({ input: child.stdout })
  const pending = new Map()
  let nextId = 1
  let failure
  let stopping = false
  let stderr = ''
  let closed
  const exit = new Promise((resolve) => { closed = resolve })
  const fail = (error) => {
    if (failure || stopping) return
    failure = error
    clearTimeout(timer)
    for (const request of pending.values()) request.reject(error)
    pending.clear()
    child.kill('SIGKILL')
  }
  const timer = setTimeout(() => fail(new Error('Codex hook approval timed out after 20 seconds')), 20000)
  child.stderr.on('data', (chunk) => { stderr = (stderr + chunk.toString()).slice(-16000) })
  child.on('error', (error) => fail(new Error(`Codex app-server could not run: ${error.message}`, { cause: error })))
  child.stdin.on('error', (error) => fail(new Error(`Codex app-server input failed: ${error.message}`, { cause: error })))
  child.stdout.on('error', (error) => fail(new Error(`Codex app-server output failed: ${error.message}`, { cause: error })))
  child.on('close', (code, signal) => {
    if (!stopping) fail(new Error(`Codex app-server exited before hook approval completed (${code ?? signal})${stderr.trim() ? `: ${stderr.trim()}` : ''}`))
    closed()
  })
  lines.on('line', (line) => {
    if (failure || stopping) return
    let payload
    try { payload = JSON.parse(line) } catch (error) {
      fail(new Error(`Codex app-server returned invalid JSON: ${error.message}`, { cause: error }))
      return
    }
    if (!payload || typeof payload !== 'object') {
      fail(new Error('Codex app-server returned a malformed message'))
      return
    }
    if (payload.id === undefined && typeof payload.method === 'string') return
    const request = pending.get(payload.id)
    if (!request || payload.method) {
      fail(new Error(`Codex app-server returned an unexpected message ID: ${payload.id}`))
      return
    }
    pending.delete(payload.id)
    if (payload.error) {
      const error = new Error(`Codex ${request.method} failed (${payload.error.code ?? 'unknown'}): ${payload.error.message ?? 'unknown RPC error'}`)
      request.reject(error)
      fail(error)
    } else if (!Object.hasOwn(payload, 'result')) {
      const error = new Error(`Codex ${request.method} response has no result`)
      request.reject(error)
      fail(error)
    } else request.resolve(payload.result)
  })
  const write = (message) => child.stdin.write(`${JSON.stringify(message)}\n`)
  return {
    request(method, params) {
      if (failure) return Promise.reject(failure)
      const id = nextId++
      return new Promise((resolve, reject) => {
        pending.set(id, { method, resolve, reject })
        write({ method, id, params })
      })
    },
    notify(method) { write({ method, params: {} }) },
    async close() {
      stopping = true
      clearTimeout(timer)
      lines.close()
      child.stdin.destroy()
      child.kill('SIGKILL')
      await exit
    },
  }
}

function selectedHooks(result, pluginId, installedPath) {
  if (!Array.isArray(result?.data)) throw new Error('Codex hooks/list did not return a data array')
  const selected = new Map()
  for (const workspace of result.data) {
    if (!Array.isArray(workspace.hooks) || !Array.isArray(workspace.errors) || !Array.isArray(workspace.warnings)) {
      throw new Error('Codex hooks/list returned malformed workspace metadata')
    }
    if (workspace.errors.length) throw new Error(`Codex hooks/list failed: ${JSON.stringify(workspace.errors)}`)
    if (workspace.warnings.length) process.stderr.write(`${JSON.stringify({ level: 'warning', operation: 'hooks/list', pluginId, warnings: workspace.warnings })}\n`)
    for (const hook of workspace.hooks) {
      if (hook.pluginId !== pluginId) continue
      if (typeof hook.key !== 'string' || !hook.key.trim() || typeof hook.currentHash !== 'string' || !hook.currentHash.trim()) {
        throw new Error('Selected hook has no usable key or currentHash')
      }
      if (typeof hook.enabled !== 'boolean' || !['trusted', 'untrusted', 'modified'].includes(hook.trustStatus)) {
        throw new Error(`Selected hook ${hook.key} has invalid enabled or trust metadata`)
      }
      if (typeof hook.sourcePath !== 'string' || !isAbsolute(hook.sourcePath) || !existsSync(hook.sourcePath) || !within(installedPath, realpathSync(hook.sourcePath))) {
        throw new Error(`Selected hook ${hook.key} sourcePath is outside the expected installed plugin: ${hook.sourcePath}`)
      }
      if (selected.has(hook.key)) throw new Error(`Codex hooks/list repeated selected hook key ${hook.key}`)
      selected.set(hook.key, hook)
    }
  }
  return [...selected.values()]
}

export async function ensurePluginHookTrust({ repo, home, pluginId, installedPath, required = false, env = process.env }) {
  if (typeof home !== 'string' || !isAbsolute(home)) throw new Error('Hook approval requires an explicit absolute Codex home')
  if (typeof installedPath !== 'string' || !isAbsolute(installedPath)) throw new Error('Hook approval requires an absolute installedPath')
  if (typeof pluginId !== 'string' || !pluginId.trim()) throw new Error('Hook approval requires a pluginId')
  const root = realpathSync(repo)
  const destination = realpathSync(home)
  const installed = realpathSync(installedPath)
  const server = appServer(root, destination, env)
  try {
    await server.request('initialize', { clientInfo: { name: 'opl-plugin-hooks', version: '1' } })
    server.notify('initialized')
    const list = async () => selectedHooks(await server.request('hooks/list', { cwds: [root] }), pluginId, installed)
    const hooks = await list()
    if (!hooks.length && required) throw new Error('Installed plugin declares hooks but Codex discovered none')
    const pending = hooks.filter((hook) => hook.trustStatus !== 'trusted')
    if (!pending.length) return hooks
    const config = join(destination, 'config.toml')
    const expectedConfig = existsSync(config) ? realpathSync(config) : config
    if (!within(destination, expectedConfig)) throw new Error('Hook approval config.toml resolves outside the authorized Codex home')
    const written = await server.request('config/batchWrite', {
      edits: [{
        keyPath: 'hooks.state',
        value: Object.fromEntries(pending.map((hook) => [hook.key, { trusted_hash: hook.currentHash }])),
        mergeStrategy: 'upsert',
      }],
      filePath: config,
      reloadUserConfig: true,
    })
    if (typeof written?.filePath !== 'string' || !isAbsolute(written.filePath) || !existsSync(written.filePath) || realpathSync(written.filePath) !== expectedConfig) {
      throw new Error('Codex hook approval did not confirm the authorized config.toml path')
    }
    const verified = await list()
    const originals = new Map(hooks.map((hook) => [hook.key, hook]))
    if (verified.length !== hooks.length || verified.some((hook) => {
      const original = originals.get(hook.key)
      return !original || hook.currentHash !== original.currentHash || hook.enabled !== original.enabled || hook.trustStatus !== 'trusted'
    })) throw new Error('Selected hooks changed or remained untrusted after approval; refresh their discovery before retrying')
    return verified
  } catch (error) {
    throw new Error(`${pluginId}: ${error.message}`, { cause: error })
  } finally {
    await server.close()
  }
}
