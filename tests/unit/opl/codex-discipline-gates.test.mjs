import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pythonBin } from '../../../tools/runtime.mjs'

const repositoryRoot = fileURLToPath(new URL('../../../', import.meta.url))
const pluginRoot = join(repositoryRoot, 'plugins', 'opl')
const githubIssueHandler = join(
  pluginRoot,
  'scripts',
  'codex-github-issues-deferral-handler.py',
)
function runHookStatus(name, input, env = {}, root = pluginRoot) {
  try {
    const stdout = execFileSync(pythonBin(), ['-B', '-X', 'utf8', join(root, 'scripts', name)], {
      cwd: env.CODEX_PROJECT_DIR ?? pluginRoot,
      env: { ...process.env, NODE_BIN: process.execPath, CODEX_BIN: join(repositoryRoot, 'missing-test-codex'), ...env },
      input: JSON.stringify(input),
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    return { status: 0, stdout, stderr: '' }
  } catch (error) {
    return {
      status: error.status,
      stdout: error.stdout?.toString() ?? '',
      stderr: error.stderr?.toString() ?? '',
    }
  }
}

function makeProject() {
  return mkdtempSync(join(tmpdir(), 'opl-discipline-test-'))
}

function fakeCodexWithEnabledPlugin(pluginPath) {
  const dir = mkdtempSync(join(tmpdir(), 'opl-codex-cli-'))
  const file = join(dir, 'codex.mjs')
  const payload = JSON.stringify({
    installed: [
      {
        installed: true,
        enabled: true,
        source: { path: pluginPath },
      },
    ],
  })
  writeFileSync(file, `console.log(${JSON.stringify(payload)})\n`)
  return { dir, file }
}

function fakeGhIssue({ number = 42, state = 'OPEN' } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'opl-gh-cli-'))
  const file = join(dir, 'gh.mjs')
  writeFileSync(
    file,
    [
      "const [command, action, ref] = process.argv.slice(2)",
      "if (command !== 'issue' || action !== 'view') process.exit(64)",
      `if (ref !== '${number}' && !ref.endsWith('/issues/${number}')) process.exit(1)`,
      `console.log(JSON.stringify({number:${number},state:${JSON.stringify(state)},url:'https://github.com/acme/example/issues/${number}'}))`,
      '',
    ].join('\n'),
  )
  return { dir, file }
}

function writeTranscript(records) {
  const dir = mkdtempSync(join(tmpdir(), 'opl-discipline-transcript-'))
  const file = join(dir, 'transcript.jsonl')
  writeFileSync(file, `${records.map((record) => JSON.stringify(record)).join('\n')}\n`)
  return { dir, file }
}

function assistant(text) {
  return { message: { role: 'assistant', content: [{ type: 'text', text }] } }
}

function linearProof({
  toolName = 'mcp__codex_apps__linear_get_issue',
  identifier,
  title,
  success = true,
}) {
  const callId = `call-${identifier}`
  return [
    {
      type: 'function_call',
      name: toolName,
      call_id: callId,
      arguments: JSON.stringify({ id: identifier }),
    },
    {
      type: 'function_call_output',
      call_id: callId,
      output: success
        ? JSON.stringify({ issue: { identifier, title } })
        : JSON.stringify({ error: 'not found' }),
    },
  ]
}

function runResponse(text, { project, priorRecords = [], env = {} } = {}) {
  const transcript = writeTranscript([...priorRecords, assistant(text)])
  const result = runHookStatus(
    'codex-response-discipline-gate.py',
    { transcript_path: transcript.file },
    { CODEX_PROJECT_DIR: project ?? pluginRoot, ...env },
  )
  rmSync(transcript.dir, { recursive: true, force: true })
  return result
}

function responseDecision(result) {
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

test('response blocks an ephemeral deferral without a durable sink', () => {
  const decision = responseDecision(runResponse('We can defer this work.'))
  assert.equal(decision.decision, 'block')
  assert.match(decision.reason, /defer/i)
})

test('response scans native rollout messages and the supplied Stop message', () => {
  const text = 'We can defer the security fix.'
  const transcript = writeTranscript([{ type: 'response_item', payload: {
    type: 'message', role: 'assistant', channel: 'final',
    content: [{ type: 'output_text', text }],
  } }])
  try {
    for (const input of [
      { transcript_path: transcript.file },
      { last_assistant_message: text },
    ]) {
      assert.equal(responseDecision(runHookStatus('codex-response-discipline-gate.py', input)).decision, 'block')
    }
  } finally {
    rmSync(transcript.dir, { recursive: true, force: true })
  }
})

const clarification = [
  'BLOCKED release-target-1, revision assignment-7.',
  'Question: Which release target should I use?',
  'Options: staging; production',
  'Recommendation: staging',
  'Evidence: The assignment does not name a target.',
  'Constraints: Select a target before release.',
  'Action withheld: Release.',
  'Parent: /root/release-lead',
  'Independent work: Validation completed.',
  'Descendants: None.',
].join('\n')

test('a complete current clarification can stop while its scoped answer is missing', () => {
  for (const audience of ['parent', 'user']) {
    for (const waiting of ['blocked on', 'awaiting', 'pending']) {
      for (const reference of ['release-target-1', '`release-target-1`']) {
        const text = `${clarification}\nStatus: ${waiting} the ${audience} answer to ${reference}.`
        assert.deepEqual(responseDecision(runResponse(text)), { continue: true }, text)
        const evidence = text.replace('Evidence: The assignment does not name a target.',
          'Evidence: The release is blocked on this target choice.')
        assert.deepEqual(responseDecision(runResponse(evidence)), { continue: true }, evidence)
      }
    }
  }
})

test('clarification status does not hide malformed checkpoints or abandoned work', () => {
  const waiting = '\nStatus: awaiting the parent answer to release-target-1.'
  for (const text of [
    clarification.replace('Evidence: The assignment does not name a target.\n', '') + waiting,
    clarification + waiting.replace('release-target-1', 'another-question'),
    clarification + waiting.replace('release-target-1', '`another-question`'),
    clarification.replace('Recommendation: staging', 'Recommendation: guess') + waiting,
    clarification + waiting + '\nThe security fix is pending implementation.',
    clarification + waiting + '\nWe can defer the security fix.',
    clarification.replace('Evidence: The assignment does not name a target.',
      'Evidence: We can defer the security fix.') + waiting,
    clarification.replace('Evidence: The assignment does not name a target.',
      'Evidence: The security fix is pending implementation.') + waiting,
    clarification.replace('Evidence: The assignment does not name a target.',
      'Evidence: The release is blocked on this target choice. The security fix is pending implementation.') + waiting,
    clarification.replace('Evidence: The assignment does not name a target.',
      'Evidence: The unrelated task is awaiting the parent answer to release-target-1.extra.') + waiting,
    clarification.replace('Evidence: The assignment does not name a target.',
      'Evidence: The unrelated task is awaiting the parent answer to `release-target-1.extra`.') + waiting,
  ]) {
    assert.equal(responseDecision(runResponse(text)).decision, 'block', text)
  }
})

test('response blocks leaving discovered work alone without a durable sink', () => {
  for (const text of [
    'I’ll leave that unrelated issue alone.',
    'I am leaving it alone.',
    'I left those failures unresolved.',
    'Leave the existing errors unaddressed.',
  ]) {
    const decision = responseDecision(runResponse(text, { env: { DISCIPLINE_DEFERRAL_HANDLERS: '' } }))
    assert.equal(decision.decision, 'block', text)
    assert.match(decision.reason, /leaving work unresolved/u)
  }
})

test('response permits preservation of user configuration and resolved failures', () => {
  for (const text of [
    'Your user configuration is unchanged.',
    'Leave your user configuration unchanged.',
    'I fixed the existing failures and all checks passed.',
  ]) {
    assert.deepEqual(responseDecision(runResponse(text)), { continue: true }, text)
  }
})

test('instruction review waits until the turn attempts to stop', () => {
  const home = makeProject()
  const turn = { session_id: 'review-session', turn_id: 'review-turn' }
  const environment = { CODEX_HOME: home }
  try {
    const edit = runHookStatus('codex-skill-review-gate.py', {
      ...turn,
      hook_event_name: 'PostToolUse',
      tool_name: 'apply_patch',
      tool_input: { command: '*** Begin Patch\n*** Update File: SKILL.md\n@@\n+Updated\n*** End Patch' },
      tool_response: { exit_code: 0 },
    }, environment)
    assert.deepEqual(JSON.parse(edit.stdout), { continue: true })

    const stop = runHookStatus('codex-skill-review-gate.py', {
      ...turn, hook_event_name: 'Stop',
    }, environment)
    assert.equal(JSON.parse(stop.stdout).decision, 'block')
    assert.match(JSON.parse(stop.stdout).reason, /\$opl:agent-instructions/u)

    const repeated = runHookStatus('codex-skill-review-gate.py', {
      ...turn, hook_event_name: 'Stop',
    }, environment)
    assert.deepEqual(JSON.parse(repeated.stdout), { continue: true })
  } finally {
    rmSync(home, { recursive: true, force: true })
  }
})

test('a later instruction edit in the same turn queues another review', () => {
  const home = makeProject()
  const turn = { session_id: 'review-session', turn_id: 'review-turn' }
  const environment = { CODEX_HOME: home }
  const postTool = (tool_name, command) => JSON.parse(runHookStatus('codex-skill-review-gate.py', {
    ...turn,
    hook_event_name: 'PostToolUse',
    tool_name,
    tool_input: { command },
    tool_response: { exit_code: 0 },
  }, environment).stdout)
  const stop = () => JSON.parse(runHookStatus('codex-skill-review-gate.py', {
    ...turn, hook_event_name: 'Stop',
  }, environment).stdout)
  const patch = (path) => `*** Begin Patch\n*** Update File: ${path}\n@@\n+Updated\n*** End Patch`
  try {
    assert.deepEqual(postTool('apply_patch', patch('SKILL.md')), { continue: true })
    assert.deepEqual(postTool('apply_patch', patch('README.md')), { continue: true })
    assert.equal(stop().decision, 'block')

    assert.deepEqual(postTool('Read', 'Read SKILL.md for the requested review'), { continue: true })
    assert.deepEqual(postTool('apply_patch', patch('README.md')), { continue: true })
    assert.deepEqual(stop(), { continue: true })

    assert.deepEqual(postTool('apply_patch', patch('AGENTS.md')), { continue: true })
    assert.deepEqual(postTool('apply_patch', patch('README.md')), { continue: true })
    assert.equal(stop().decision, 'block')
    assert.deepEqual(stop(), { continue: true })
  } finally {
    rmSync(home, { recursive: true, force: true })
  }
})

test('post-tool skill and AGENTS edits are recorded for final review', () => {
  const home = makeProject()
  const environment = { CODEX_HOME: home }
  try {
    for (const [index, path] of ['C:/work/skills/example/SKILL.md', 'C:/work/AGENTS.md', 'SKILL.md', 'AGENTS.md'].entries()) {
      const turn = { session_id: 'review-session', turn_id: 'patch-' + index }
      const result = runHookStatus('codex-skill-review-gate.py', {
        ...turn,
        hook_event_name: 'PostToolUse',
        tool_name: 'apply_patch',
        tool_input: { command: '*** Begin Patch\n*** Update File: ' + path + '\n@@\n+Updated\n*** End Patch' },
        tool_response: { exit_code: 0 },
      }, environment)
      assert.equal(result.status, 0, result.stderr)
      assert.deepEqual(JSON.parse(result.stdout), { continue: true })
      const stop = runHookStatus('codex-skill-review-gate.py', { ...turn, hook_event_name: 'Stop' }, environment)
      assert.equal(JSON.parse(stop.stdout).decision, 'block')
    }
    for (const tool_name of ['Edit', 'Write']) {
      const turn = { session_id: 'review-session', turn_id: tool_name }
      const result = runHookStatus('codex-skill-review-gate.py', {
        ...turn, hook_event_name: 'PostToolUse', tool_name,
        tool_input: { file_path: 'AGENTS.md' },
      }, environment)
      assert.deepEqual(JSON.parse(result.stdout), { continue: true })
      const stop = runHookStatus('codex-skill-review-gate.py', { ...turn, hook_event_name: 'Stop' }, environment)
      assert.equal(JSON.parse(stop.stdout).decision, 'block')
    }
  } finally {
    rmSync(home, { recursive: true, force: true })
  }
})

test('unrelated and failed edits do not queue an instruction review', () => {
  const home = makeProject()
  const environment = { CODEX_HOME: home }
  try {
    for (const [index, input] of [
      { tool_name: 'Bash', tool_input: { command: 'Get-Content C:/work/AGENTS.md' } },
      { tool_name: 'apply_patch', tool_input: { command: '*** Begin Patch\n*** Update File: C:/work/README.md\n@@\n+Updated\n*** End Patch' } },
      { tool_name: 'apply_patch', tool_input: { command: '*** Begin Patch\n*** Update File: SKILL.md\n@@\n+Updated\n*** End Patch' }, tool_response: { exit_code: 1 } },
    ].entries()) {
      const turn = { session_id: 'review-session', turn_id: 'negative-' + index }
      const result = runHookStatus('codex-skill-review-gate.py', {
        ...turn, hook_event_name: 'PostToolUse', ...input,
      }, environment)
      assert.equal(result.status, 0, result.stderr)
      assert.deepEqual(JSON.parse(result.stdout), { continue: true })
      const stop = runHookStatus('codex-skill-review-gate.py', { ...turn, hook_event_name: 'Stop' }, environment)
      assert.deepEqual(JSON.parse(stop.stdout), { continue: true })
    }
  } finally {
    rmSync(home, { recursive: true, force: true })
  }
})

test('dangerous shell blocks PowerShell root, home, parent, and glob removals', () => {
  for (const command of [
    'Remove-Item -LiteralPath "C:\\" -Recurse -Force',
    'Remove-Item -LiteralPath $HOME -Recurse -Force',
    'Remove-Item -LiteralPath "..\\shared" -Recurse -Force',
    'Remove-Item -Path "C:\\work\\*" -Recurse -Force',
    'rtk proxy powershell -Command "Remove-Item -LiteralPath $HOME -Recurse"',
    'git push origin main --force',
    'git push -f origin main',
  ]) {
    const result = runHookStatus('codex-dangerous-shell-gate.py', { tool_input: { command } })
    assert.equal(result.status, 2, `${command}\n${result.stderr}`)
  }
})

test('dangerous shell permits explicit repository cleanup in PowerShell', () => {
  const result = runHookStatus('codex-dangerous-shell-gate.py', {
    tool_input: { command: 'Remove-Item -LiteralPath "./build output" -Recurse -Force' },
  })
  assert.equal(result.status, 0, result.stderr)
})

test('skill sigil gate discovers skills and respects same-line literal bypasses', () => {
  const project = makeProject()
  const skill = join(project, '.agents', 'skills', 'native-example')
  mkdirSync(skill, { recursive: true })
  writeFileSync(join(skill, 'SKILL.md'), '---\nname: native-example\n---\nInstructions.\n')
  const path = join(project, 'AGENTS.md')
  try {
    writeFileSync(path, 'Run `native-example`.\n')
    const result = runHookStatus('codex-skill-reference-sigil-gate.py', {
      tool_input: { file_path: path },
    }, { CODEX_PROJECT_DIR: project })
    assert.equal(result.status, 2, result.stderr)
    assert.match(result.stderr, /dollar-sigil/u)
    writeFileSync(path, 'The literal `native-example`. <!-- skill-reference-sigil-bypass -->\n')
    assert.equal(runHookStatus('codex-skill-reference-sigil-gate.py', {
      tool_input: { file_path: path },
    }, { CODEX_PROJECT_DIR: project }).status, 0)
  } finally {
    rmSync(project, { recursive: true, force: true })
  }
})

test('artifact policy keeps bypasses and per-token allowlist semantics', () => {
  const plugin = makeProject()
  mkdirSync(join(plugin, 'scripts'))
  writeFileSync(join(plugin, 'scripts', 'codex-discipline-gate.exceptions.txt'), '# A real release name\nTauri v2\n')
  const env = { OPL_DISCIPLINE_PLUGIN_ROOT: plugin, DISCIPLINE_DEFERRAL_HANDLERS: '' }
  try {
    for (const text of ['Use Tauri v2.', 'Deferred work. <!-- discipline-bypass -->']) {
      assert.equal(runHookStatus('codex-artifact-discipline-gate.py', {
        tool_input: { content: text },
      }, env).status, 0, text)
    }
    const result = runHookStatus('codex-artifact-discipline-gate.py', {
      tool_input: { content: 'Use Tauri v2 for our v1.' },
    }, env)
    assert.equal(result.status, 2)
    assert.match(result.stderr, /token: "v1"/u)
    assert.doesNotMatch(result.stderr, /token: "v2"/u)
  } finally {
    rmSync(plugin, { recursive: true, force: true })
  }
})

test('GitHub Issues provider handles an existing open issue', () => {
  const project = makeProject()
  const fakeGh = fakeGhIssue()
  try {
    const result = runHookStatus(
      'codex-github-issues-deferral-handler.py',
      {
        protocol_version: 1,
        content: 'Deferred to #42.',
        repository_root: project,
      },
      { CODEX_PROJECT_DIR: project, GH_BIN: fakeGh.file },
    )
    assert.equal(result.status, 0, result.stderr)
    assert.deepEqual(JSON.parse(result.stdout), {
      handled: true,
      handler: 'github-issues',
    })
  } finally {
    rmSync(project, { recursive: true, force: true })
    rmSync(fakeGh.dir, { recursive: true, force: true })
  }
})

test('core discovers the GitHub Issues provider from the enabled OPL plugin', () => {
  const project = makeProject()
  const fakeGh = fakeGhIssue()
  const fakeCodex = fakeCodexWithEnabledPlugin(pluginRoot)
  try {
    const decision = responseDecision(
      runResponse('Deferred to #42.', {
        project,
        env: {
          CODEX_BIN: fakeCodex.file,
          GH_BIN: fakeGh.file,
        },
      }),
    )
    assert.equal(decision.continue, true)
  } finally {
    rmSync(project, { recursive: true, force: true })
    rmSync(fakeGh.dir, { recursive: true, force: true })
    rmSync(fakeCodex.dir, { recursive: true, force: true })
  }
})

test('core response accepts a deferral backed by an existing GitHub issue', () => {
  const project = makeProject()
  const fakeGh = fakeGhIssue()
  try {
    const decision = responseDecision(
      runResponse('Deferred to #42.', {
        project,
        env: {
          DISCIPLINE_DEFERRAL_HANDLERS: githubIssueHandler,
          GH_BIN: fakeGh.file,
        },
      }),
    )
    assert.equal(decision.continue, true)
  } finally {
    rmSync(project, { recursive: true, force: true })
    rmSync(fakeGh.dir, { recursive: true, force: true })
  }
})

test('GitHub Issues provider leaves a missing issue for the catch-all to reject', () => {
  const project = makeProject()
  const fakeGh = fakeGhIssue()
  try {
    const decision = responseDecision(
      runResponse('Deferred to #404.', {
        project,
        env: {
          DISCIPLINE_DEFERRAL_HANDLERS: githubIssueHandler,
          GH_BIN: fakeGh.file,
        },
      }),
    )
    assert.equal(decision.decision, 'block')
    assert.match(decision.reason, /GitHub issue #404 could not be verified/u)
  } finally {
    rmSync(project, { recursive: true, force: true })
    rmSync(fakeGh.dir, { recursive: true, force: true })
  }
})

test('GitHub Issues provider rejects a closed issue as a deferral sink', () => {
  const project = makeProject()
  const fakeGh = fakeGhIssue({ state: 'CLOSED' })
  try {
    const decision = responseDecision(
      runResponse('Deferred to https://github.com/acme/example/issues/42.', {
        project,
        env: {
          DISCIPLINE_DEFERRAL_HANDLERS: githubIssueHandler,
          GH_BIN: fakeGh.file,
        },
      }),
    )
    assert.equal(decision.decision, 'block')
    assert.match(decision.reason, /GitHub issue .* is CLOSED/u)
  } finally {
    rmSync(project, { recursive: true, force: true })
    rmSync(fakeGh.dir, { recursive: true, force: true })
  }
})

test('core response blocks Linear proof when no provider handles Linear', () => {
  const title = 'Add photon torpedoes to shuttle'
  const decision = responseDecision(
    runResponse(`Deferred to ONE-7: ${title}`, {
      priorRecords: linearProof({ identifier: 'ONE-7', title }),
      env: { DISCIPLINE_DEFERRAL_HANDLERS: '' },
    }),
  )
  assert.equal(decision.decision, 'block')
})

test('response blocks Linear syntax without tool-result proof', () => {
  const decision = responseDecision(
    runResponse('Deferred to ONE-7: Add photon torpedoes to shuttle'),
  )
  assert.equal(decision.decision, 'block')
  assert.match(decision.reason, /Linear proof|ONE-7/i)
})

test('response blocks a Linear title mismatch', () => {
  const decision = responseDecision(
    runResponse('Deferred to ONE-7: Add photon torpedoes to shuttle', {
      priorRecords: linearProof({
        identifier: 'ONE-7',
        title: 'Add coffee maker to shuttle',
      }),
    }),
  )
  assert.equal(decision.decision, 'block')
})

test('response rejects matching Linear text outside a tool result', () => {
  const identifier = 'ONE-7'
  const title = 'Add photon torpedoes to shuttle'
  const decision = responseDecision(
    runResponse(`Deferred to ${identifier}: ${title}`, {
      priorRecords: [
        {
          type: 'function_call',
          name: 'mcp__codex_apps__linear_get_issue',
          call_id: 'call-ONE-7',
          arguments: JSON.stringify({ id: identifier }),
        },
        {
          type: 'assistant_note',
          call_id: 'call-ONE-7',
          content: { identifier, title },
        },
      ],
    }),
  )
  assert.equal(decision.decision, 'block')
})

test('response blocks MVP framing even beside a valid sink', () => {
  const title = 'Add photon torpedoes to shuttle'
  const decision = responseDecision(
    runResponse(`Deferred to ONE-7: ${title}\nGood enough for v1.`, {
      priorRecords: linearProof({ identifier: 'ONE-7', title }),
    }),
  )
  assert.equal(decision.decision, 'block')
  assert.match(decision.reason, /MVP framing/)
})

test('artifact blocks a newly inserted TODO without a sink', () => {
  const result = runHookStatus('codex-artifact-discipline-gate.py', {
    tool_input: {
      file_path: '/tmp/example.js',
      new_string: '// TODO: repair the warp core',
    },
  })
  assert.equal(result.status, 2)
  assert.match(result.stderr, /TODO/)
})

test('artifact blocks an unresolved TODO introduced by apply_patch', () => {
  const result = runHookStatus('codex-artifact-discipline-gate.py', {
    tool_input: {
      patch: [
        '*** Begin Patch',
        '*** Update File: example.js',
        '@@',
        '+// TODO: repair the warp core',
        '*** End Patch',
      ].join('\n'),
    },
  })
  assert.equal(result.status, 2)
  assert.match(result.stderr, /TODO/)
})

test('artifact catch-all blocks Linear TODO without a Linear provider', () => {
  const title = 'Repair warp core'
  const transcript = writeTranscript(
    linearProof({
      toolName: 'mcp__codex_apps__linear_save_issue',
      identifier: 'ENG-1778',
      title,
    }),
  )
  try {
    const result = runHookStatus(
      'codex-artifact-discipline-gate.py',
      {
        transcript_path: transcript.file,
        tool_input: {
          file_path: '/tmp/example.js',
          new_string: `// TODO ENG-1778: ${title}`,
        },
      },
      { DISCIPLINE_DEFERRAL_HANDLERS: '' },
    )
    assert.equal(result.status, 2)
  } finally {
    rmSync(transcript.dir, { recursive: true, force: true })
  }
})
