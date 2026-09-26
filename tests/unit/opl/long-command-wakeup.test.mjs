import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const runner = fileURLToPath(new URL('../../../plugins/opl/skills/long-command-wakeup/scripts/run_and_wake.py', import.meta.url))
const python = process.env.PYTHON_BIN ?? (process.platform === 'win32' ? 'python' : 'python3')

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function removeFixture(path) {
  let failure
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      rmSync(path, { recursive: true, force: true, maxRetries: 1, retryDelay: 50 })
      return
    } catch (error) {
      failure = error
      if (error?.code !== 'EPERM' && error?.code !== 'ENOTEMPTY') throw error
      await wait(100)
    }
  }
  throw failure
}

async function readCompletedStatus(path, timeoutMilliseconds = 10_000) {
  const deadline = Date.now() + timeoutMilliseconds
  let lastError
  while (Date.now() < deadline) {
    try {
      const value = JSON.parse(readFileSync(path, 'utf8'))
      if (['success', 'failed', 'timed_out', 'launch_failed'].includes(value.state) && ['submitted', 'failed'].includes(value.queue?.state)) return value
    } catch (error) {
      lastError = error
    }
    await wait(25)
  }
  assert.fail(`result did not reach a completed state: ${lastError?.message ?? path}`)
}

function fixture(t) {
  const parent = mkdtempSync(join(tmpdir(), 'long-wake-test-'))
  const root = join(parent, 'workspace é')
  mkdirSync(root)
  t.after(() => removeFixture(parent))
  const commandLog = join(root, 'codex-calls.jsonl')
  const fakeCodexScript = join(root, 'fake-codex.mjs')
  writeFileSync(fakeCodexScript, `#!/usr/bin/env node
import { appendFileSync } from 'node:fs'
const args = process.argv.slice(2)
if (JSON.stringify(args) === JSON.stringify(['queue', '--help'])) process.exit(0)
if (args[0] !== 'queue') process.exit(91)
appendFileSync(process.env.WAKE_TEST_COMMAND_LOG, JSON.stringify(args) + '\\n')
if (process.env.WAKE_TEST_QUEUE_FAIL === '1') {
  process.stderr.write('fixture queue failure')
  process.exit(19)
}
process.stdout.write('queued fixture message')
`)
  chmodSync(fakeCodexScript, 0o755)
  let fakeCodex = fakeCodexScript
  if (process.platform === 'win32') {
    fakeCodex = join(root, 'fake-codex.cmd')
    writeFileSync(fakeCodex, `@echo off\r\n"${process.execPath}" "%~dp0fake-codex.mjs" %*\r\n`)
  }
  const resultRoot = join(root, 'results with spaces')
  mkdirSync(resultRoot)
  const invoke = (command, { timeoutSeconds = 5, extraEnv = {}, threadArg = true } = {}) => spawnSync(python, [
    runner,
    'start',
    ...(threadArg ? ['--thread', '123e4567-e89b-12d3-a456-426614174000'] : []),
    '--timeout-seconds',
    String(timeoutSeconds),
    '--cwd',
    root,
    '--result-root',
    resultRoot,
    '--',
    ...command,
  ], {
    cwd: root,
    encoding: 'utf8',
    env: {
      ...process.env,
      CODEX_BIN: fakeCodex,
      WAKE_TEST_COMMAND_LOG: commandLog,
      ...extraEnv,
    },
  })
  const calls = () => existsSync(commandLog)
    ? readFileSync(commandLog, 'utf8').trim().split(/\r?\n/u).filter(Boolean).map(JSON.parse)
    : []
  return { root, resultRoot, commandLog, invoke, calls }
}

test('detached command records output and queues one bounded completion message', async (t) => {
  const f = fixture(t)
  const secretOutput = 'command output must not enter the queue message'
  const result = f.invoke([python, '-c', `import sys; print(${JSON.stringify(secretOutput)}); print('diagnostic', file=sys.stderr)`])
  assert.equal(result.status, 0, result.stderr)
  const receipt = JSON.parse(result.stdout)
  assert.equal(typeof receipt.pid, 'number')
  assert.ok(receipt.resultDir.startsWith(f.resultRoot))

  const status = await readCompletedStatus(join(receipt.resultDir, 'status.json'))
  assert.equal(status.schemaVersion, 1)
  assert.equal(status.state, 'success', JSON.stringify(status))
  assert.equal(status.exitCode, 0)
  assert.equal(status.queue.state, 'submitted')
  assert.match(readFileSync(join(receipt.resultDir, 'stdout.log'), 'utf8'), /command output must not enter/u)
  assert.match(readFileSync(join(receipt.resultDir, 'stderr.log'), 'utf8'), /diagnostic/u)
  assert.equal(f.calls().length, 1)
  assert.deepEqual(f.calls()[0].slice(0, 3), ['queue', '--thread', '123e4567-e89b-12d3-a456-426614174000'])
  const message = f.calls()[0][4]
  assert.match(message, /state=success/u)
  assert.match(message, /Inspect the saved artifacts once/u)
  assert.doesNotMatch(message, new RegExp(secretOutput, 'u'))
})

test('nonzero command exit is preserved and still wakes the thread', async (t) => {
  const f = fixture(t)
  const result = f.invoke([python, '-c', 'import sys; sys.exit(7)'])
  assert.equal(result.status, 0, result.stderr)
  const receipt = JSON.parse(result.stdout)
  const status = await readCompletedStatus(join(receipt.resultDir, 'status.json'))
  assert.equal(status.state, 'failed')
  assert.equal(status.exitCode, 7)
  assert.equal(status.queue.state, 'submitted')
  assert.equal(f.calls().length, 1)
})

test('timeout kills the command tree before a descendant can produce later output', async (t) => {
  const f = fixture(t)
  const marker = join(f.root, 'descendant-survived.txt')
  const child = `import time; time.sleep(2); open(${JSON.stringify(marker)}, 'w', encoding='utf-8').write('bad')`
  const parent = `import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', ${JSON.stringify(child)}]); time.sleep(30)`
  const result = f.invoke([python, '-c', parent], { timeoutSeconds: 0.25 })
  assert.equal(result.status, 0, result.stderr)
  const receipt = JSON.parse(result.stdout)
  const status = await readCompletedStatus(join(receipt.resultDir, 'status.json'))
  assert.equal(status.state, 'timed_out')
  assert.equal(status.timedOut, true)
  assert.equal(status.queue.state, 'submitted')
  await wait(2_250)
  assert.equal(existsSync(marker), false)
})

test('launch failure and queue failure remain inspectable without retries', async (t) => {
  const launch = fixture(t)
  const launchResult = launch.invoke([join(launch.root, 'missing executable')])
  assert.equal(launchResult.status, 0, launchResult.stderr)
  const launchReceipt = JSON.parse(launchResult.stdout)
  const launchStatus = await readCompletedStatus(join(launchReceipt.resultDir, 'status.json'))
  assert.equal(launchStatus.state, 'launch_failed')
  assert.equal(launchStatus.queue.state, 'submitted')
  assert.equal(launch.calls().length, 1)

  const queue = fixture(t)
  const queueResult = queue.invoke([python, '-c', 'print("done")'], { extraEnv: { WAKE_TEST_QUEUE_FAIL: '1' } })
  assert.equal(queueResult.status, 0, queueResult.stderr)
  const queueReceipt = JSON.parse(queueResult.stdout)
  const queueStatus = await readCompletedStatus(join(queueReceipt.resultDir, 'status.json'))
  assert.equal(queueStatus.state, 'success')
  assert.equal(queueStatus.queue.state, 'failed')
  assert.equal(queueStatus.queue.exitCode, 19)
  assert.match(readFileSync(join(queueReceipt.resultDir, 'queue.log'), 'utf8'), /fixture queue failure/u)
  assert.equal(queue.calls().length, 1)
})

test('queue capability failure prevents the detached command from starting', (t) => {
  const f = fixture(t)
  const marker = join(f.root, 'should-not-exist.txt')
  const result = f.invoke([python, '-c', `open(${JSON.stringify(marker)}, 'w').write('bad')`], {
    extraEnv: { CODEX_BIN: join(f.root, 'missing-codex') },
  })
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /codex queue is unavailable/iu)
  assert.equal(existsSync(marker), false)
  assert.deepEqual(f.calls(), [])
})

test('thread identity defaults to the Codex-provided environment', async (t) => {
  const f = fixture(t)
  const thread = '0199a751-84f9-7e31-a6bc-0cd0a232c648'
  const result = f.invoke([python, '-c', 'print("done")'], {
    threadArg: false,
    extraEnv: { CODEX_THREAD_ID: thread },
  })
  assert.equal(result.status, 0, result.stderr)
  const receipt = JSON.parse(result.stdout)
  const status = await readCompletedStatus(join(receipt.resultDir, 'status.json'))
  assert.equal(status.state, 'success')
  assert.deepEqual(f.calls()[0].slice(0, 3), ['queue', '--thread', thread])
})

test('cleanup failure records a terminal timeout and submits one queue request', (t) => {
  const f = fixture(t)
  const resultDir = join(f.root, 'direct-worker-result')
  mkdirSync(resultDir)
  const probe = `
import argparse, importlib.util, json, os, subprocess, sys
from pathlib import Path
runner, result_dir = sys.argv[1:]
spec = importlib.util.spec_from_file_location("run_and_wake", runner)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class NeverExits:
    pid = 4242
    returncode = None
    def poll(self): return None
    def wait(self, timeout=None): raise subprocess.TimeoutExpired("fixture", timeout)

if os.name == "nt":
    module.os.name = "nt"
    def fail_cleanup(*args, **kwargs): raise subprocess.TimeoutExpired("taskkill", kwargs.get("timeout"))
    cleanup_expected = "taskkill"
else:
    module.os.name = "posix"
    module.os.killpg = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("fixture cleanup failure"))
    def fail_cleanup(*args, **kwargs): return subprocess.CompletedProcess(args[0], 0, "", "")
    cleanup_expected = "SIGTERM"
module.subprocess.run = fail_cleanup
cleanup_error = module.terminate_process_tree(NeverExits())
if os.name == "nt":
    module.subprocess.run = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", "")
    taskkill_success = module.terminate_process_tree(NeverExits())
else:
    taskkill_success = None
taskkill_final_wait = module.wait_for_final_exit(NeverExits())

module.subprocess.run = lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("queue", kwargs.get("timeout"), output=b"stdout", stderr=b"stderr"))
queue_timeout = module.queue_message(sys.executable, "thread", "failed", Path(result_dir))

submissions = []
callback_artifacts_ready = False
def submit_or_fail_cleanup(args, **kwargs):
    global callback_artifacts_ready
    if os.name == "nt" and args[0] == "taskkill":
        raise subprocess.TimeoutExpired("taskkill", kwargs.get("timeout"))
    status = json.loads((Path(result_dir) / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "timed_out"
    assert status["queue"]["state"] == "pending-submission"
    assert all((Path(result_dir) / name).is_file() for name in ["stdout.log", "stderr.log", "queue.log"])
    callback_artifacts_ready = True
    submissions.append(args)
    return subprocess.CompletedProcess(args, 0, "submitted", "")
module.subprocess.run = submit_or_fail_cleanup
module.subprocess.Popen = lambda *args, **kwargs: NeverExits()
module.run_worker(argparse.Namespace(timeout_seconds=0.01, command=["--", sys.executable, "-c", "pass"], cwd=str(Path(result_dir).parent), result_dir=result_dir, codex_bin=sys.executable, thread="thread"))
status = json.loads((Path(result_dir) / "status.json").read_text(encoding="utf-8"))
print(json.dumps({"cleanupError": cleanup_error, "cleanupExpected": cleanup_expected, "taskkillSuccess": taskkill_success, "taskkillFinalWait": taskkill_final_wait, "queueTimeout": queue_timeout, "status": status, "submissions": submissions, "callbackArtifactsReady": callback_artifacts_ready, "queueLog": (Path(result_dir) / "queue.log").read_text(encoding="utf-8")}))
`
  const result = spawnSync(python, ['-c', probe, runner, resultDir], { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  const observed = JSON.parse(result.stdout)
  assert.match(observed.cleanupError, new RegExp(observed.cleanupExpected, 'u'))
  assert.equal(observed.taskkillSuccess, null)
  assert.match(observed.taskkillFinalWait, /final cleanup wait/u)
  assert.equal(observed.queueTimeout[0].state, 'failed')
  assert.equal(observed.queueTimeout[1], 'stdoutstderr')
  assert.equal(observed.status.state, 'timed_out')
  assert.equal(observed.status.timedOut, true)
  assert.equal(observed.status.cleanup.state, 'failed')
  assert.match(observed.status.cleanup.error, new RegExp(observed.cleanupExpected, 'u'))
  assert.equal(observed.status.commandPid, 4242)
  assert.equal(observed.status.queue.state, 'submitted')
  assert.equal(observed.submissions.length, 1)
  assert.equal(observed.callbackArtifactsReady, true)
  assert.equal(observed.queueLog, 'submitted')
})
