import test from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pythonBin } from '../../../tools/runtime.mjs'

const scripts = fileURLToPath(new URL('../../../plugins/opl/skills/slop-buster/scripts/', import.meta.url))

function run(name, args = [], env = {}) {
  return spawnSync(pythonBin(), ['-B', '-X', 'utf8', join(scripts, `${name}.py`), ...args], {
    encoding: 'utf8',
    env: { ...process.env, ...env },
  })
}

function fixture(fn) {
  const directory = mkdtempSync(join(tmpdir(), 'slop native 研究-'))
  try {
    fn(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

function stateFields(result) {
  assert.equal(result.status, 0, result.stderr)
  return Object.fromEntries(result.stdout.split('\n').filter(Boolean).map((line) => {
    const tab = line.indexOf('\t')
    return [line.slice(0, tab), line.slice(tab + 1)]
  }))
}

test('slop state uses native home defaults without creating state', () => fixture((directory) => {
  const result = run('inspect-state', [], {
    CODEX_HOME: '', SLOP_BUSTER_STATE_DIR: '', HOME: directory, USERPROFILE: directory,
  })
  const fields = stateFields(result)
  assert.equal(fields.stateDir, join(directory, '.codex', 'slop-buster'))
  assert.equal(fields.hasFiles, 'false')
  assert.equal(fields.latestSlopFile, '')
  assert.equal(fields.latestSourceLog, '')
}))

test('slop state reports newest slop file and first source-log anchor', () => fixture((directory) => {
  const state = join(directory, 'custom state')
  mkdirSync(state)
  const older = join(state, 'slop-older.md')
  const newer = join(state, 'slop-newer.md')
  const source = join(directory, 'session with spaces.jsonl')
  writeFileSync(older, 'SOURCE_LOG: old.jsonl\n4\n')
  writeFileSync(newer, `SOURCE_LOG: ${source}\r\nSOURCE_LOG: ignored.jsonl\r\n12\r\n`)
  utimesSync(older, 100, 100)
  utimesSync(newer, 200, 200)
  const fields = stateFields(run('inspect-state', [], { SLOP_BUSTER_STATE_DIR: state }))
  assert.equal(fields.hasFiles, 'true')
  assert.equal(fields.latestSlopFile, newer)
  assert.equal(fields.latestSourceLog, source)
}))

test('slop log listing honors CODEX_HOME and strict modification-time cutoff', () => fixture((directory) => {
  const sessions = join(directory, 'sessions', '2026', '09')
  mkdirSync(sessions, { recursive: true })
  const older = join(sessions, 'old.jsonl')
  const newer = join(sessions, 'new.jsonl')
  writeFileSync(older, '{}\n')
  writeFileSync(newer, '{}\n')
  utimesSync(older, 100, 100)
  utimesSync(newer, 200, 200)
  const all = run('list-codex-session-logs', [], { CODEX_HOME: directory })
  assert.equal(all.status, 0, all.stderr)
  assert.deepEqual(all.stdout.trimEnd().split('\n'), [newer, older])
  const recent = run('list-codex-session-logs', ['--newer-than-log', older], { CODEX_HOME: directory })
  assert.equal(recent.status, 0, recent.stderr)
  assert.deepEqual(recent.stdout.trimEnd().split('\n'), [newer])
}))

test('slop log filter preserves source line anchors and candidate framing', () => fixture((directory) => {
  const path = join(directory, 'session.jsonl')
  const records = [
    { type: 'response_item', payload: { type: 'message', role: 'user', content: '# AGENTS.md instructions for test' } },
    { type: 'event_msg', payload: { type: 'user_message', message: 'That answer was wrong.' } },
    { type: 'response_item', payload: { type: 'message', id: 'msg_123', role: 'assistant', content: 'I fixed the error.' } },
    { type: 'event_msg', payload: { type: 'agent_message', message: 'Here is a pleasant update.' } },
    { type: 'event_msg', payload: { type: 'agent_message', message: 'Retrying after the failure.' } },
    { type: 'function_call_output', output: 'error' },
  ]
  const source = records.map((record) => JSON.stringify(record))
  writeFileSync(path, `${source.join('\n')}\n`)
  const result = run('filter-log-file', [path], { SLOP_BUSTER_MAX_OUTPUT_CHARS: '2500' })
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(result.stdout.trimEnd().split('\n'), [
    `SLOP_BUSTER_CANDIDATE_START\tlogPath=${path}\tmaxOutputChars=2500`,
    `[2] truncated=false ${source[1]}`,
    `[3] truncated=false ${source[2]}`,
    `[5] truncated=false ${source[4]}`,
    'SLOP_BUSTER_CANDIDATE_END\tlinesEmitted=3',
  ])
}))

test('slop filter truncates emitted records and rejects invalid limits', () => fixture((directory) => {
  const path = join(directory, 'session.jsonl')
  const source = JSON.stringify({ type: 'event_msg', payload: { type: 'user_message', message: 'A long correction. '.repeat(10) } })
  writeFileSync(path, `${source}\n`)
  const result = run('filter-log-file', [path], { SLOP_BUSTER_MAX_OUTPUT_CHARS: '80' })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout.split('\n')[1], `[1] truncated=true ${source.slice(0, 80)}`)
  const invalid = run('filter-log-file', [path], { SLOP_BUSTER_MAX_OUTPUT_CHARS: '0' })
  assert.equal(invalid.status, 2)
  assert.match(invalid.stderr, /must be a positive integer/)
}))

test('slop listing rejects incomplete arguments and missing source directories', () => fixture((directory) => {
  assert.equal(run('list-codex-session-logs', ['--newer-than-log'], { CODEX_HOME: directory }).status, 2)
  const missing = run('list-codex-session-logs', [], { CODEX_HOME: directory })
  assert.equal(missing.status, 1)
  assert.match(missing.stderr, /Codex session directory does not exist/)
}))
