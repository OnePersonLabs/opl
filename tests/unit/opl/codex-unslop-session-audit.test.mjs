import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { pythonBin } from '../../../tools/runtime.mjs'

const extractor = fileURLToPath(new URL('../../../plugins/opl/skills/unslop-session-audit/scripts/extract-session.py', import.meta.url))

test('session audit extracts UTF-8 to the native temporary directory by default', () => {
  const project = mkdtempSync(join(tmpdir(), 'unslop audit native '))
  try {
    const nativeTemp = join(project, 'temporary output é')
    mkdirSync(nativeTemp)
    const session = join(project, 'rollout-native-session.jsonl')
    const records = [
      { type: 'session_meta', payload: { id: 'native-session', cwd: project } },
      { type: 'response_item', payload: { type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Check résumé 🧪' }] } },
    ]
    writeFileSync(session, records.map((record) => JSON.stringify(record)).join('\n'))
    const result = spawnSync(pythonBin(), ['-B', extractor, session], {
      encoding: 'utf8', windowsHide: true,
      env: { ...process.env, TMP: nativeTemp, TEMP: nativeTemp, TMPDIR: nativeTemp, PYTHONUTF8: '0' },
    })
    assert.equal(result.status, 0, result.stderr)
    const receipt = JSON.parse(result.stdout)
    assert.equal(receipt.out, join(nativeTemp, 'unslop-session-native-session.txt'))
    assert.equal(receipt.agent, 'codex')
    assert.equal(receipt.emitted_turns, 2)
    assert.match(readFileSync(receipt.out, 'utf8'), /Check résumé 🧪/u)
  } finally { rmSync(project, { recursive: true, force: true }) }
})

test('session audit preserves explicit output paths and reports tail truncation', () => {
  const project = mkdtempSync(join(tmpdir(), 'unslop audit explicit '))
  try {
    const session = join(project, 'claude-session.jsonl')
    const output = join(project, 'chosen output.txt')
    const records = Array.from({ length: 20 }, (_, index) => ({ type: 'user', message: { content: `turn ${index}: ${'x'.repeat(150)}` } }))
    writeFileSync(session, records.map((record) => JSON.stringify(record)).join('\n'))
    const result = spawnSync(pythonBin(), ['-B', '-X', 'utf8', extractor, session, '--out', output, '--max-kb', '1'], { encoding: 'utf8', windowsHide: true })
    assert.equal(result.status, 0, result.stderr)
    const receipt = JSON.parse(result.stdout)
    assert.equal(receipt.out, output)
    assert.ok(receipt.dropped_oldest > 0)
    assert.match(readFileSync(output, 'utf8'), /NOTICE:.*oldest turns elided/u)
    assert.match(readFileSync(output, 'utf8'), /turn 19:/u)
  } finally { rmSync(project, { recursive: true, force: true }) }
})
