#!/usr/bin/env node

import { execFileSync, spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { syncOplAgentProfiles } from './sync-opl-agent-profiles.mjs'

const path = 'plugins/opl/AGENTS.md'

function git(...args) {
  return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
}

function hasHead() {
  return spawnSync('git', ['rev-parse', '--verify', 'HEAD'], { stdio: 'ignore' }).status === 0
}

function normalize(text) {
  return text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n')
}

function version(text, { allowMissing = false } = {}) {
  const occurrences = [...text.matchAll(/opl-instructions-version/g)]
  if (allowMissing && occurrences.length === 0) return null
  const markers = [...text.matchAll(/^<!-- opl-instructions-version: ([1-9]\d*) -->$/gm)]
  if (occurrences.length !== 1 || markers.length !== 1) {
    throw new Error('OPL AGENTS.md must contain exactly one valid <!-- opl-instructions-version: N --> marker with a positive integer revision.')
  }
  return { value: BigInt(markers[0][1]), marker: markers[0][0] }
}

try {
  const root = git('rev-parse', '--show-toplevel').trim()
  const sync = syncOplAgentProfiles(root, { stage: true, requireStagedAgents: true })
  if (sync.changed) process.stdout.write(`Synchronized agent profiles and staged ${path}.\n`)

  const stagedChanges = git('diff', '--cached', '--name-only', '--', path).trim()
  if (stagedChanges) {
    if (!git('ls-files', '--stage', '--', path).trim()) {
      throw new Error('OPL AGENTS.md is deleted from the index. Restore and stage the versioned instruction file before committing.')
    }
    const staged = normalize(git('show', `:${path}`))
    const stagedVersion = version(staged)
    const existingHead = hasHead()
    const previousEntry = existingHead ? git('ls-tree', 'HEAD', '--', path).trim() : ''
    const previous = previousEntry ? normalize(git('show', `HEAD:${path}`)) : ''
    const previousVersion = version(previous, { allowMissing: true })
    if (!previousVersion) {
      if (existingHead && stagedVersion.value !== 1n) throw new Error('Initial OPL instruction version adoption must use revision 1.')
    } else {
      if (stagedVersion.value < previousVersion.value) throw new Error('OPL instruction revision must not decrease. Restore or increment the revision, stage the file, and retry.')
      const changedContent = staged.replace(stagedVersion.marker, '') !== previous.replace(previousVersion.marker, '')
      if (changedContent && stagedVersion.value <= previousVersion.value) {
        const requiredVersion = previousVersion.value + 1n
        const workingPath = join(root, path)
        const working = normalize(readFileSync(workingPath, 'utf8'))
        const workingVersion = version(working)
        const nextVersion = workingVersion.value > requiredVersion ? workingVersion.value : requiredVersion
        const bumped = working.replace(workingVersion.marker, `<!-- opl-instructions-version: ${nextVersion} -->`)
        writeFileSync(workingPath, bumped, 'utf8')
        git('add', '--', path)
        process.stdout.write(`Bumped the OPL instruction revision to ${nextVersion} and staged ${path}.\n`)
      }
    }
  }
} catch (error) {
  const detail = error.stderr?.toString().trim()
  process.stderr.write(`${detail || error.message}\n`)
  process.exitCode = 1
}
