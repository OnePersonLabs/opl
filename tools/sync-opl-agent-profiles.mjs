#!/usr/bin/env node

import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const instructionPath = 'plugins/opl/AGENTS.md'
const agentDirectory = 'plugins/opl/agents'
const profilesHeading = '### Subagent Profiles'

function git(root, ...args) {
  return execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
}

function tomlString(source, key, file) {
  const matches = [...source.matchAll(new RegExp(`^${key}\\s*=\\s*("(?:[^"\\\\]|\\\\.)*")\\s*$`, 'gm'))]
  if (matches.length !== 1) throw new Error(`${file}: expected exactly one top-level ${key} basic string`)
  try {
    return JSON.parse(matches[0][1])
  } catch (error) {
    throw new Error(`${file}: cannot parse ${key} as a basic string: ${error.message}`)
  }
}

function renderProfiles(root) {
  const directory = join(root, agentDirectory)
  const files = readdirSync(directory).filter((file) => file.endsWith('.toml')).sort()
  if (files.length === 0) throw new Error(`${agentDirectory}: no agent TOML files found`)

  const profiles = files.map((file) => {
    const path = join(directory, file)
    const source = readFileSync(path, 'utf8')
    const name = tomlString(source, 'name', file)
    const description = tomlString(source, 'description', file)
    return `- ${JSON.stringify(name)}: ${JSON.stringify(description)}`
  })

  return `${profilesHeading}\n\nUse a specific subagent when its responsibility fits the assignment:\n\n${profiles.join('\n')}\n`
}

function requireStagedAgentSources(root) {
  const unstaged = git(root, 'diff', '--name-only', '--', agentDirectory).trim()
  const untracked = git(root, 'ls-files', '--others', '--exclude-standard', '--', agentDirectory).trim()
  if (unstaged || untracked) {
    throw new Error(`Stage all changed files in ${agentDirectory} before syncing profiles, so the generated list matches the commit.`)
  }
}

function replaceProfiles(contents, rendered) {
  const headingIndex = contents.indexOf(profilesHeading)
  if (headingIndex < 0 || contents.indexOf(profilesHeading, headingIndex + profilesHeading.length) >= 0) {
    throw new Error(`Expected exactly one ${profilesHeading} section in ${instructionPath}`)
  }
  const sectionEnd = contents.indexOf('\n### ', headingIndex + profilesHeading.length)
  if (sectionEnd < 0) throw new Error(`${profilesHeading} must be followed by another level-three section`)
  return (contents.slice(0, headingIndex) + rendered + contents.slice(sectionEnd)).replace(/\n+$/u, '\n')
}

function bumpRevision(contents) {
  const matches = [...contents.matchAll(/^<!-- opl-instructions-version: ([1-9]\d*) -->$/gm)]
  if (matches.length !== 1 || contents.match(/opl-instructions-version/g)?.length !== 1) {
    throw new Error('OPL AGENTS.md must contain exactly one valid instruction version marker before profile sync.')
  }
  const revision = BigInt(matches[0][1]) + 1n
  return contents.replace(matches[0][0], `<!-- opl-instructions-version: ${revision} -->`)
}

export function syncOplAgentProfiles(root, { stage = false, requireStagedAgents = false } = {}) {
  const path = join(root, instructionPath)
  if (!existsSync(path) || !existsSync(join(root, agentDirectory))) return { changed: false }
  if (requireStagedAgents) requireStagedAgentSources(root)
  const contents = readFileSync(path, 'utf8')
  const updated = replaceProfiles(contents, renderProfiles(root))
  if (updated === contents) return { changed: false }

  const versioned = bumpRevision(updated)
  writeFileSync(path, versioned, 'utf8')
  if (stage) {
    try {
      git(root, 'add', '--', instructionPath)
    } catch (error) {
      throw new Error(`Updated ${instructionPath}, but could not stage it: ${error.stderr?.toString().trim() || error.message}`)
    }
  }
  return { changed: true, staged: stage }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  try {
    const root = git(process.cwd(), 'rev-parse', '--show-toplevel').trim()
    const result = syncOplAgentProfiles(root, { stage: process.argv.includes('--stage') })
    console.log(result.changed ? `Updated ${instructionPath}${result.staged ? ' and staged it' : ''}.` : `${instructionPath} already matches the agent TOML files.`)
  } catch (error) {
    process.stderr.write(`${error.message}\n`)
    process.exitCode = 1
  }
}
