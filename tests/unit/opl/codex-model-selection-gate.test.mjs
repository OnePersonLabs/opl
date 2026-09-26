import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { pythonBin } from '../../../tools/runtime.mjs'

const pluginRoot = fileURLToPath(new URL('../../../plugins/opl/', import.meta.url))
const script = join(pluginRoot, 'scripts', 'codex-model-selection-gate.py')

function check(command) {
  const result = spawnSync(pythonBin(), ['-B', '-X', 'utf8', script], {
    input: JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command } }),
    encoding: 'utf8',
    windowsHide: true,
  })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

function reason(command) {
  const output = check(command)
  assert.equal(output.hookSpecificOutput?.permissionDecision, 'deny', command)
  return output.hookSpecificOutput.permissionDecisionReason
}

function missing(command) {
  return reason(command).match(/needs an explicit ([^.]+) for this child task/u)?.[1]
}

test('rejects a direct exec with either explicit setting missing', () => {
  assert.equal(missing('codex exec "inspect this"'), 'model, model_reasoning_effort')
  assert.equal(missing('codex exec -m gpt-6-astra "inspect this"'), 'model_reasoning_effort')
  assert.equal(missing('codex exec -c model_reasoning_effort=medium "inspect this"'), 'model')
  assert.equal(missing('codex exec --model= "inspect this"'), 'model, model_reasoning_effort')
  assert.equal(missing('codex exec -m gpt-6-sol -c model_reasoning_effort= "inspect this"'), 'model_reasoning_effort')
  assert.equal(missing('codex exec -m "" -c model_reasoning_effort=medium "inspect this"'), 'model')
})

test('accepts both explicit settings through flags and config overrides', () => {
  for (const command of [
    'codex exec -m gpt-6-astra -c model_reasoning_effort="low" "inspect this"',
    'codex exec --model=gpt-6-sol --config=model_reasoning_effort=high "implement this"',
    'codex exec -c model=gpt-6-astra -c model_reasoning_effort=medium "review this"',
    'codex -m gpt-6-sol exec -c model_reasoning_effort=medium "implement this"',
    'codex exec fork -m gpt-6-sol -c model_reasoning_effort=xhigh 01a094a7-0cbc-72a0-9935-9e3f2b7f0169 "continue"',
    'codex exec resume --model gpt-6-astra -c model_reasoning_effort=high --last "continue"',
    'codex exec review -m gpt-6-sol -c model_reasoning_effort=high --uncommitted',
    '& "C:\\Program Files\\Codex\\codex.exe" exec -m gpt-6-astra -c "model_reasoning_effort=high" "check"',
    'codex exec `\n -m gpt-6-astra `\n -c model_reasoning_effort=medium "check"',
    'codex exec \\\n -m gpt-6-astra \\\n -c model_reasoning_effort=medium "check"',
  ]) assert.deepEqual(check(command), {}, command)
})

test('prompt text cannot impersonate CLI settings', () => {
  assert.match(reason('codex exec "Discuss --model=gpt-6-astra and -c model_reasoning_effort=low"'), /model.*effort/iu)
  assert.match(reason('codex exec -m gpt-6-astra write a guide to -c model_reasoning_effort=low'), /effort/iu)
})

test('recognizes subcommands and Windows/POSIX shell chains', () => {
  for (const command of [
    'codex exec fork 01a094a7-0cbc-72a0-9935-9e3f2b7f0169 "continue"',
    'codex exec resume --last',
    'codex exec review --uncommitted',
    'codex e inspect',
    'Get-Location; codex exec "inspect"',
    'pwd && codex exec "inspect"',
    "cat <<'EOF'\ncodex exec ignored\nEOF\ncodex exec inspect",
    '# <<EOF\ncodex exec inspect',
    'echo x # <<EOF\ncodex exec inspect',
  ]) assert.match(reason(command), /model.*effort/iu, command)
})

test('leaves unrelated text and shell commands alone', () => {
  for (const command of [
    'echo "codex exec -m gpt-6-sol"',
    "echo ';' codex exec inspect",
    "cat <<'EOF'\ncodex exec inspect\nEOF",
    'cat <<\\EOF\ncodex exec inspect\nEOF',
    'rg "codex exec" docs',
    'codex --version',
    'npm test',
  ]) assert.deepEqual(check(command), {}, command)
})

test('recognizes a direct exec through the env wrapper', () => {
  assert.equal(missing('env codex exec inspect'), 'model, model_reasoning_effort')
  assert.equal(missing('env FOO=bar codex exec inspect'), 'model, model_reasoning_effort')
  assert.equal(missing('CODEX_HOME=/tmp/isolated codex exec inspect'), 'model, model_reasoning_effort')
  assert.deepEqual(check('env FOO=bar codex exec -m gpt-6-sol -c model_reasoning_effort=medium inspect'), {})
})

test('manifest registers the gate for Bash on Windows and POSIX', () => {
  const manifest = JSON.parse(readFileSync(join(pluginRoot, 'hooks', 'hooks.json'), 'utf8'))
  const handler = manifest.hooks.PreToolUse
    .flatMap((group) => group.hooks)
    .find((hook) => hook.command.includes('codex-model-selection-gate.py'))
  assert.ok(handler)
  assert.match(handler.command, /^python3 -B -X utf8 /u)
  assert.match(handler.commandWindows, /^python -B -X utf8 /u)
})

test('malformed hook input blocks with an actionable error', () => {
  for (const input of ['{', '[]', '{"tool_input": []}']) {
    const result = spawnSync(pythonBin(), ['-B', '-X', 'utf8', script], {
      input,
      encoding: 'utf8',
      windowsHide: true,
    })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /codex-model-selection-gate:.*(JSON|object|tool_input)/iu)
  }
})
