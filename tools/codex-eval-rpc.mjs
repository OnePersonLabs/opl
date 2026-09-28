import { spawn } from 'node:child_process'
import readline from 'node:readline'
import { codexCommand } from './runtime.mjs'

/** Streaming app-server transport for finite behavioral evaluations. */
export function evaluationServer({ cwd, onMessage, timeoutMs = 180000, command, env = process.env }) {
  const [executable, ...args] = command ?? codexCommand(['-c', 'project_doc_max_bytes=0', 'app-server', '--listen', 'stdio://'])
  const child = spawn(executable, args, { cwd, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  const pending = new Map()
  const lines = readline.createInterface({ input: child.stdout })
  let nextId = 1
  let stderr = ''
  let stopping = false
  let failure
  let rejectFailure
  let resolveExit
  const exited = new Promise((resolve) => { resolveExit = resolve })
  const failed = new Promise((_, reject) => { rejectFailure = reject })
  // Callers race operations against this promise; suppress an idle rejection.
  failed.catch(() => {})
  const fail = (error) => {
    if (failure || stopping) return
    failure = error
    rejectFailure(error)
    for (const waiter of pending.values()) waiter.reject(error)
    pending.clear()
    child.kill('SIGKILL')
  }
  const timer = setTimeout(() => fail(new Error(`Evaluation exceeded ${timeoutMs}ms`)), timeoutMs)
  const write = (message) => child.stdin.write(`${JSON.stringify(message)}\n`)
  const api = {
    failed,
    request(method, params) {
      if (failure) return Promise.reject(failure)
      const id = nextId++
      return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); write({ id, method, params }) })
    },
    notify(method, params = {}) { write({ method, params }) },
    respond(id, result) { write({ id, result }) },
    async close() { stopping = true; clearTimeout(timer); lines.close(); child.stdin.destroy(); child.kill('SIGKILL'); await exited },
  }
  child.stderr.on('data', (chunk) => { stderr = (stderr + chunk).slice(-4000) })
  child.on('error', fail)
  child.stdin.on('error', fail)
  child.on('close', (code) => { resolveExit(); if (!stopping) fail(new Error(`Evaluation server exited ${code}: ${stderr}`)) })
  lines.on('line', (line) => {
    let message
    try { message = JSON.parse(line) } catch (error) { fail(new Error(`Invalid app-server JSON: ${error.message}`)); return }
    if (message.id !== undefined && !message.method) {
      const waiter = pending.get(message.id)
      if (!waiter) { fail(new Error(`Unexpected response ${message.id}`)); return }
      pending.delete(message.id)
      if (message.error) waiter.reject(new Error(JSON.stringify(message.error)))
      else waiter.resolve(message.result)
    } else {
      Promise.resolve().then(() => onMessage?.(message, api)).catch(fail)
    }
  })
  return api
}
