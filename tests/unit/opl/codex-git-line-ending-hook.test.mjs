import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { pythonBin } from '../../../tools/runtime.mjs'

const pluginRoot = fileURLToPath(new URL('../../../plugins/opl/', import.meta.url))
const hookPath = `${pluginRoot}scripts/codex-git-line-ending-hook.py`

function runHook(payload) {
  return spawnSync(pythonBin(), ['-B', '-X', 'utf8', hookPath], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    windowsHide: true,
  })
}

function additionalContext(result) {
  assert.equal(result.status, 0, result.stderr)
  if (!result.stdout) return null
  const output = JSON.parse(result.stdout)
  assert.deepEqual(Object.keys(output), ['hookSpecificOutput'])
  assert.equal(output.hookSpecificOutput.hookEventName, 'PostToolUse')
  return output.hookSpecificOutput.additionalContext
}

function payload(toolResponse, extra = {}) {
  return {
    hook_event_name: 'PostToolUse',
    tool_name: 'Bash',
    tool_input: { command: 'git add -- file.txt' },
    tool_response: toolResponse,
    ...extra,
  }
}

test('the current Git warning form in tool output returns one scoped repair directive', () => {
  for (const warning of [
    "warning: in the working copy of 'src/app.py', CRLF will be replaced by LF the next time Git touches it",
    "warning: in the working copy of 'src/app.py', LF will be replaced by CRLF the next time Git touches it",
  ]) {
    const message = additionalContext(runHook(payload(`Exit code: 0\nOutput:\n${warning}\n`)))
    assert.match(message, /fix the cause in this task/u)
    assert.match(message, /preserve staged and other dirty work/u)
    assert.match(message, /do not paste it into shell syntax/u)
  }
})

test('the older Git warning form also matches both conversion directions', () => {
  for (const warning of [
    'warning: CRLF will be replaced by LF in src/app.py.\nThe file will have its original line endings in your working directory.',
    'warning: LF will be replaced by CRLF in src/app.py.\nThe file will have its original line endings in your working directory.',
  ]) {
    assert.match(additionalContext(runHook(payload(warning))), /Git reported a CRLF conversion/u)
  }
})

test('ordinary output, same-ending text, and warning text outside tool output stay silent', () => {
  const warning = "warning: in the working copy of 'src/app.py', LF will be replaced by CRLF the next time Git touches it"
  for (const [toolResponse, extra] of [
    ['git add completed', {}],
    ['warning: permission denied', {}],
    [warning, { tool_name: 'MCP__git__add' }],
    ['', { tool_input: { command: `echo "${warning}"` } }],
    ['> ' + warning, {}],
    ['warning: in the working copy of file.txt, LF will be replaced by LF the next time Git touches it', {}],
  ]) {
    assert.equal(additionalContext(runHook(payload(toolResponse, extra))), null)
  }
})

test('manifest registers the detector for PostToolUse Bash on Windows and POSIX', () => {
  const manifest = JSON.parse(readFileSync(`${pluginRoot}hooks/hooks.json`, 'utf8'))
  const group = manifest.hooks.PostToolUse.find((entry) => entry.matcher === 'Bash'
    && entry.hooks.some((handler) => handler.command.includes('codex-git-line-ending-hook.py')))
  assert.ok(group)
  const handler = group.hooks.find((entry) => entry.command.includes('codex-git-line-ending-hook.py'))
  assert.match(handler.command, /^python3 -B -X utf8 /u)
  assert.match(handler.commandWindows, /^python -B -X utf8 /u)
  assert.equal(handler.timeout, 3)
})
