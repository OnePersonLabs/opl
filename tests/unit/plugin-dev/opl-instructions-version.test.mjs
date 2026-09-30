import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const guard = fileURLToPath(new URL('../../../tools/check-opl-instructions-version.mjs', import.meta.url))
const instructionPath = 'plugins/opl/AGENTS.md'
const instructions = (revision, body = '# Instructions\n') => `<!-- opl-instructions-version: ${revision} -->\n${body}`

function check(t, { before = instructions(1), staged, working }) {
  const root = mkdtempSync(join(tmpdir(), 'opl-version-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const git = (...args) => execFileSync('git', args, { cwd: root, stdio: 'pipe' })
  git('init', '--quiet')
  git('config', 'user.name', 'Test')
  git('config', 'user.email', 'test@example.invalid')
  git('config', 'core.autocrlf', 'false')
  mkdirSync(join(root, 'plugins', 'opl'), { recursive: true })
  writeFileSync(join(root, instructionPath), before)
  git('add', instructionPath)
  git('-c', 'core.hooksPath=/dev/null', 'commit', '--quiet', '-m', 'baseline')
  if (staged === null) {
    git('rm', instructionPath)
  } else if (staged !== undefined) {
    writeFileSync(join(root, instructionPath), staged)
    git('add', instructionPath)
  } else {
    writeFileSync(join(root, 'unrelated.txt'), 'unrelated')
    git('add', 'unrelated.txt')
  }
  if (working !== undefined) writeFileSync(join(root, instructionPath), working)
  return spawnSync(process.execPath, [guard], { cwd: root, encoding: 'utf8' })
}

test('accepts a staged revision bump with instruction changes', (t) => {
  assert.equal(check(t, { staged: instructions(2, '# Updated\n') }).status, 0)
})

test('pre-commit syncs agent TOMLs, bumps the revision, and stages the instruction file', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'opl-agent-profile-sync-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const git = (...args) => execFileSync('git', args, { cwd: root, stdio: 'pipe' })
  git('init', '--quiet')
  git('config', 'user.name', 'Test')
  git('config', 'user.email', 'test@example.invalid')
  const agents = join(root, 'plugins', 'opl', 'agents')
  mkdirSync(agents, { recursive: true })
  const profile = join(agents, 'opl-example.toml')
  writeFileSync(profile, 'name = "opl-example"\ndescription = "Example role."\n')
  const file = join(root, instructionPath)
  const initial = instructions(1, '### Subagent Profiles\n\nUse a specific subagent when its responsibility fits the assignment:\n\n- "opl-example": "Example role."\n\n### Root Agent Control Plane\n')
  writeFileSync(file, initial)
  git('add', instructionPath, 'plugins/opl/agents/opl-example.toml')
  git('-c', 'core.hooksPath=/dev/null', 'commit', '--quiet', '-m', 'baseline')

  writeFileSync(profile, 'name = "opl-example"\ndescription = "Updated role description."\n')
  const unstaged = spawnSync(process.execPath, [guard], { cwd: root, encoding: 'utf8' })
  assert.equal(unstaged.status, 1)
  assert.match(unstaged.stderr, /Stage all changed files in plugins\/opl\/agents/u)
  assert.equal(readFileSync(file, 'utf8'), initial, 'unstaged profile edits must not alter or stage AGENTS.md')

  git('add', 'plugins/opl/agents/opl-example.toml')
  const result = spawnSync(process.execPath, [guard], { cwd: root, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /Synchronized agent profiles and staged plugins\/opl\/AGENTS\.md/u)
  const updated = readFileSync(file, 'utf8')
  assert.match(updated, /^<!-- opl-instructions-version: 2 -->/u)
  assert.match(updated, /- opl-example: Updated role description\./u)
  assert.equal(execFileSync('git', ['diff', '--cached', '--name-only', '--', instructionPath], { cwd: root, encoding: 'utf8' }).trim(), instructionPath)
  const repeated = spawnSync(process.execPath, [guard], { cwd: root, encoding: 'utf8' })
  assert.equal(repeated.status, 0, repeated.stderr)
  assert.doesNotMatch(repeated.stdout, /Synchronized agent profiles/u)
  assert.match(readFileSync(file, 'utf8'), /^<!-- opl-instructions-version: 2 -->/u)
})

test('accepts an inherited revision in an unborn repository', (t) => {
  const root = mkdtempSync(join(tmpdir(), 'opl-extraction-version-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const git = (...args) => execFileSync('git', args, { cwd: root, stdio: 'pipe' })
  git('init', '--quiet')
  mkdirSync(join(root, 'plugins', 'opl'), { recursive: true })
  writeFileSync(join(root, instructionPath), instructions(10))
  git('add', instructionPath)
  const result = spawnSync(process.execPath, [guard], { cwd: root, encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
})

test('automatically bumps and stages the revision when staged instructions changed', (t) => {
  const result = check(t, { staged: instructions(1, '# Updated\n'), working: instructions(2, '# Updated\n') })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /Bumped the OPL instruction revision to 2 and staged/u)
})

test('unrelated staged changes do not inspect an unstaged instruction edit', (t) => {
  assert.equal(check(t, { working: 'invalid local work' }).status, 0)
})

test('normalizes BOM and CRLF differences and auto-bumps other staged content edits', (t) => {
  assert.equal(check(t, { staged: '\uFEFF' + instructions(1).replaceAll('\n', '\r\n') }).status, 0)
  const result = check(t, { staged: instructions(1, '# Instructions \n'), working: instructions(2, '# Instructions \n') })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /Bumped the OPL instruction revision/u)
})

test('accepts initial unversioned adoption only as revision 1', (t) => {
  assert.equal(check(t, { before: '# Previous\n', staged: instructions(1) }).status, 0)
  assert.equal(check(t, { before: '# Previous\n', staged: instructions(2) }).status, 1)
})

test('rejects missing, duplicate, and malformed markers', (t) => {
  for (const staged of ['# Missing\n', instructions(1) + instructions(2), instructions(0), instructions('1.1'), instructions('01'), instructions('-1')]) {
    assert.equal(check(t, { staged }).status, 1, staged)
  }
})

test('rejects a deleted instruction file with an actionable error', (t) => {
  const result = check(t, { staged: null })
  assert.equal(result.status, 1)
  assert.match(result.stderr, /Restore and stage the versioned instruction file/)
})

test('rejects version-only decreases and permits version-only increases', (t) => {
  assert.equal(check(t, { before: instructions(2), staged: instructions(1) }).status, 1)
  assert.equal(check(t, { staged: instructions(2) }).status, 0)
})
