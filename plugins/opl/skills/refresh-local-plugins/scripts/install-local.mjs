#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, readlinkSync, realpathSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { codexCommand } from './codex-command.mjs'
import { ensurePluginHookTrust } from './codex-hooks.mjs'

const marketplaceFiles = [
  '.agents/plugins/marketplace.json',
  '.agents/plugins/api_marketplace.json',
]

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8').replace(/^\uFEFF/u, ''))
  } catch (error) {
    throw new Error(`Cannot read JSON at ${path}: ${error.message}`, { cause: error })
  }
}

function within(root, candidate) {
  const path = relative(root, candidate)
  return path === '' || (path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path))
}

function validName(name) {
  return typeof name === 'string' && /^[a-z0-9][a-z0-9._-]*$/iu.test(name)
}

function canonicalDestination(path) {
  const absolute = resolve(path)
  if (existsSync(absolute)) return realpathSync(absolute)
  if (dirname(absolute) === absolute) throw new Error(`Cannot resolve the destination filesystem root: ${absolute}`)
  return join(canonicalDestination(dirname(absolute)), basename(absolute))
}

function sameContents(source, installed) {
  if (!existsSync(installed)) return false
  const sourceStat = lstatSync(source)
  const installedStat = lstatSync(installed)
  if (sourceStat.isSymbolicLink() || installedStat.isSymbolicLink()) {
    return sourceStat.isSymbolicLink() && installedStat.isSymbolicLink() && readlinkSync(source) === readlinkSync(installed)
  }
  if (sourceStat.isDirectory() || installedStat.isDirectory()) {
    if (!sourceStat.isDirectory() || !installedStat.isDirectory()) return false
    const sourceNames = readdirSync(source).sort()
    const installedNames = readdirSync(installed).sort()
    return sourceNames.length === installedNames.length && sourceNames.every((name, index) =>
      name === installedNames[index] && sameContents(join(source, name), join(installed, name)))
  }
  return sourceStat.isFile() && installedStat.isFile() && sourceStat.size === installedStat.size && readFileSync(source).equals(readFileSync(installed))
}

function installedCopy(home, marketplace, name, source) {
  const manifest = ['.codex-plugin/plugin.json']
    .map((path) => join(source, path)).find(existsSync)
  if (!manifest) throw new Error(`${name}: no plugin manifest found in ${source}`)
  const version = readJson(manifest).version
  if (typeof version !== 'string' || !version || !validName(version)) throw new Error(`${name}: invalid plugin version in ${manifest}`)
  return join(home, 'plugins', 'cache', marketplace, name, version)
}

function preparationFor(repo) {
  const manifest = join(realpathSync(repo), 'package.json')
  if (!existsSync(manifest)) return undefined
  const pkg = readJson(manifest)
  if (pkg.scripts?.['plugin:prepare-local'] === undefined) return undefined
  if (typeof pkg.scripts['plugin:prepare-local'] !== 'string' || !pkg.scripts['plugin:prepare-local'].trim()) {
    throw new Error('plugin:prepare-local must be a nonempty package script')
  }
  const manager = (pkg.packageManager ?? 'npm').split('@')[0]
  if (!['npm', 'pnpm', 'yarn', 'bun'].includes(manager)) throw new Error(`Unsupported preparation package manager: ${manager}`)
  return { command: `${manager} run plugin:prepare-local` }
}

function installationPlan({ repo = process.cwd(), plugins, targetHome, beforePreparation = false }) {
  if (!Array.isArray(plugins) || !plugins.length) plugins = ['modified']
  if (!targetHome) {
    targetHome = join(homedir(), '.codex')
    if (!existsSync(targetHome) || !statSync(targetHome).isDirectory()) throw new Error(`User-level Codex home does not exist: ${targetHome}`)
  }
  if (!isAbsolute(targetHome)) throw new Error('--target-home requires an absolute Codex home path')
  if (plugins.includes('all') && plugins.length !== 1) throw new Error('--plugin all must be used alone')
  if (plugins.includes('modified') && plugins.length !== 1) throw new Error('--plugin modified must be used alone')
  const root = realpathSync(repo)
  const home = canonicalDestination(targetHome)
  const cache = canonicalDestination(join(home, 'plugins', 'cache'))
  const manifestPath = marketplaceFiles.map((path) => join(root, path)).find(existsSync)
  if (!manifestPath) throw new Error(`No local marketplace manifest found in ${root}; expected ${marketplaceFiles.join(', ')}`)
  const marketplace = readJson(manifestPath)
  if (!validName(marketplace.name) || !Array.isArray(marketplace.plugins) || !marketplace.plugins.length) {
    throw new Error(`Invalid marketplace name or plugins array in ${manifestPath}`)
  }
  const entries = new Map()
  for (const entry of marketplace.plugins) {
    if (!validName(entry?.name) || entries.has(entry.name)) throw new Error(`Invalid or duplicate plugin name in ${manifestPath}: ${entry?.name}`)
    entries.set(entry.name, entry)
  }
  const names = ['all', 'modified'].includes(plugins[0]) ? [...entries.keys()] : [...new Set(plugins)]
  const selected = names.map((name) => {
    const entry = entries.get(name)
    if (!entry) throw new Error(`Unknown plugin ${name}; available: ${[...entries.keys()].join(', ')}`)
    const path = typeof entry.source === 'string' ? entry.source : entry.source?.source === 'local' ? entry.source.path : undefined
    if (typeof path !== 'string' || !path || isAbsolute(path)) throw new Error(`${name}: refresh requires a relative local plugin source`)
    if ((path !== '.' && !path.startsWith('./')) || path.split(/[\\/]/u).includes('..')) {
      throw new Error(`${name}: local source path must stay beneath the marketplace root and use ./ (optional for the marketplace root): ${path}`)
    }
    const source = beforePreparation ? canonicalDestination(resolve(root, path)) : realpathSync(resolve(root, path))
    if (!within(root, source)) throw new Error(`${name}: plugin source escapes marketplace root: ${source}`)
    if ((!beforePreparation || existsSync(source)) && !statSync(source).isDirectory()) throw new Error(`${name}: plugin source is not a directory: ${source}`)
    if (within(source, home)) throw new Error(`${name}: the Codex home must not be inside the plugin source: ${home}`)
    if (within(cache, source) || within(source, cache)) throw new Error(`${name}: target cache must not overlap the plugin source: ${cache}`)
    return { name, pluginId: `${name}@${marketplace.name}`, source }
  })
  const changed = plugins[0] === 'modified'
    ? selected.filter((plugin) => {
      const installedPlugin = join(home, 'plugins', 'cache', marketplace.name, plugin.name)
      return existsSync(installedPlugin) && statSync(installedPlugin).isDirectory()
        && (beforePreparation || !sameContents(plugin.source, installedCopy(home, marketplace.name, plugin.name, plugin.source)))
    })
    : selected
  return { root, home, marketplace: marketplace.name, plugins: changed }
}

function codexJson(args, { root, home }, environment) {
  const env = { ...environment, CODEX_HOME: home }
  const [command, ...commandArgs] = codexCommand(args, { env })
  const result = spawnSync(command, commandArgs, { cwd: root, env, encoding: 'utf8', windowsHide: true })
  if (result.error) throw new Error(`Codex ${args.join(' ')} could not run: ${result.error.message}`, { cause: result.error })
  if (result.status !== 0) throw new Error(`Codex ${args.join(' ')} failed (${result.status ?? result.signal}): ${result.stderr.trim() || result.stdout.trim()}`)
  if (result.stderr.trim()) process.stderr.write(result.stderr)
  try {
    return JSON.parse(result.stdout)
  } catch (error) {
    throw new Error(`Codex ${args.join(' ')} returned invalid JSON: ${error.message}`, { cause: error })
  }
}

function command(executable, args) {
  const result = spawnSync(executable, args, { encoding: 'utf8', windowsHide: true })
  if (result.error) throw new Error(`${executable} could not run: ${result.error.message}`, { cause: result.error })
  return result
}

function pythonBin(environment) {
  return environment.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3')
}

export function reconcileOplAgents({ name, installedPath, home, env = process.env }) {
  if (name !== 'opl') return { reconciled: false }
  const pluginRoot = realpathSync(installedPath)
  const script = join(pluginRoot, 'scripts', 'codex-config-check.py')
  if (!existsSync(script)) throw new Error(`opl: installed configuration reconciler is missing: ${script}`)
  const result = spawnSync(pythonBin(env), ['-B', '-X', 'utf8', script, 'reconcile', '--home', home, '--plugin-root', pluginRoot], {
    cwd: pluginRoot,
    env,
    encoding: 'utf8',
    windowsHide: true,
  })
  if (result.error) throw new Error(`opl: agent configuration reconciliation could not run: ${result.error.message}`, { cause: result.error })
  if (result.status !== 0) {
    const detail = result.stderr.trim() || result.stdout.trim() || 'no diagnostic output'
    throw new Error(`opl: agent configuration reconciliation failed (${result.status ?? result.signal}): ${detail}`)
  }
  if (result.stderr.trim()) process.stderr.write(result.stderr)
  if (result.stdout.trim()) process.stdout.write(result.stdout)
  return { reconciled: true, pluginRoot, home }
}

function wslPath(path) {
  const result = command('wsl.exe', ['--exec', 'wslpath', '-u', path])
  if (result.status !== 0) throw new Error(`WSL could not access ${path}: ${result.stderr.trim() || result.stdout.trim()}`)
  return result.stdout.trim()
}

function windowsPath(path) {
  const result = command('wslpath', ['-w', path])
  if (result.status !== 0) throw new Error(`Windows could not access ${path}: ${result.stderr.trim() || result.stdout.trim()}`)
  return result.stdout.trim()
}

function powershellLiteral(value) { return `'${value.replaceAll("'", "''")}'` }
function posixLiteral(value) { return `'${value.replaceAll("'", "'\\''")}'` }

export function counterpartInvocation({ platform, script, repo, plugins = [], dryRun = false, translate }) {
  const extra = [...plugins.flatMap((name) => ['--plugin', name]), ...(dryRun ? ['--dry-run'] : []), '--local-only', '--registered-source']
  if (platform === 'win32') {
    const args = [translate(script), '--repo', translate(repo), ...extra]
    return { executable: 'wsl.exe', args: ['--exec', 'bash', '-lc', `node ${args.map(posixLiteral).join(' ')}`] }
  }
  const args = [translate(script), '--repo', translate(repo), ...extra]
  const invocation = `& node ${args.map(powershellLiteral).join(' ')}; exit $LASTEXITCODE`
  return {
    executable: 'powershell.exe',
    args: ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(invocation, 'utf16le').toString('base64')],
  }
}

function registeredSource(repo, env) {
  const root = realpathSync(repo)
  const manifestPath = marketplaceFiles.map((path) => join(root, path)).find(existsSync)
  if (!manifestPath) throw new Error(`No local marketplace manifest found in ${root}`)
  const marketplace = readJson(manifestPath)
  const home = join(homedir(), '.codex')
  const listed = codexJson(['plugin', 'marketplace', 'list', '--json'], { root, home }, env)
  const registered = listed.marketplaces.find((item) => item.name === marketplace.name)
  return registered?.root ?? root
}

function runCounterpart({ repo, plugins, dryRun }) {
  const script = fileURLToPath(import.meta.url)
  if (process.platform === 'win32') {
    let available
    try { available = command('wsl.exe', ['--exec', 'sh', '-lc', 'test -d "$HOME/.codex"']) }
    catch (error) {
      if (error.cause?.code === 'ENOENT') return { skipped: 'WSL is unavailable' }
      throw error
    }
    if (available.status !== 0) return { skipped: 'WSL user-level ~/.codex is absent or unavailable' }
    const invocation = counterpartInvocation({ platform: 'win32', script, repo, plugins, dryRun, translate: wslPath })
    return command(invocation.executable, invocation.args)
  }
  if (!process.env.WSL_DISTRO_NAME) return { skipped: 'No Windows counterpart outside WSL' }
  let available
  try { available = command('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', "if (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.codex') -PathType Container) { exit 0 } else { exit 1 }"]) }
  catch (error) {
    if (error.cause?.code === 'ENOENT') return { skipped: 'Windows interop is unavailable' }
    throw error
  }
  if (available.status !== 0) return { skipped: 'Windows user-level ~/.codex is absent or unavailable' }
  const invocation = counterpartInvocation({ platform: 'linux', script, repo, plugins, dryRun, translate: windowsPath })
  return command(invocation.executable, invocation.args)
}

export async function refreshUserHomes({ repo = process.cwd(), plugins = [], dryRun = false, localOnly = false, useRegisteredSource = false, env = process.env } = {}) {
  if (localOnly) return installLocal({ repo: useRegisteredSource ? registeredSource(repo, env) : repo, plugins, dryRun, env })
  const outcomes = []
  const home = join(homedir(), '.codex')
  if (existsSync(home) && statSync(home).isDirectory()) {
    try {
      const plan = await installLocal({ repo, plugins, dryRun, env })
      outcomes.push({ environment: process.platform === 'win32' ? 'Windows' : 'WSL', home: plan.home, ok: true })
    } catch (error) {
      outcomes.push({ environment: process.platform === 'win32' ? 'Windows' : 'WSL', home, ok: false, error: error.message })
      console.error(`${process.platform === 'win32' ? 'Windows' : 'WSL'}: ${error.message}`)
    }
  } else console.log(`${process.platform === 'win32' ? 'Windows' : 'WSL'}: no user-level .codex directory; skipped.`)
  try {
    const other = runCounterpart({ repo, plugins, dryRun })
    if (other.skipped) console.log(`${process.platform === 'win32' ? 'WSL' : 'Windows'}: ${other.skipped}; skipped.`)
    else {
      console.log(`${process.platform === 'win32' ? 'WSL' : 'Windows'}:`)
      if (other.stdout) process.stdout.write(other.stdout)
      if (other.stderr) process.stderr.write(other.stderr)
      outcomes.push({ environment: process.platform === 'win32' ? 'WSL' : 'Windows', ok: other.status === 0 })
      if (other.status !== 0) console.error(`${process.platform === 'win32' ? 'WSL' : 'Windows'}: refresh failed (${other.status ?? other.signal}).`)
    }
  } catch (error) {
    outcomes.push({ environment: process.platform === 'win32' ? 'WSL' : 'Windows', ok: false, error: error.message })
    console.error(`${process.platform === 'win32' ? 'WSL' : 'Windows'}: ${error.message}`)
  }
  if (outcomes.some(({ ok }) => !ok)) throw new Error('One or more user-level Codex environments could not be refreshed; see environment results above')
  if (!outcomes.length) console.log('No accessible user-level Codex home was found.')
  return outcomes
}

export async function installLocal(options) {
  const preparation = preparationFor(options.repo ?? process.cwd())
  let plan = installationPlan({ ...options, beforePreparation: Boolean(preparation) })
  if (options.dryRun) {
    console.log(JSON.stringify({ ...plan, ...(preparation ? { preparation, selectionPendingPreparation: true } : {}), dryRun: true }, null, 2))
    return plan
  }
  if (!plan.plugins.length) {
    console.log(`No modified plugins for ${plan.home}.`)
    return plan
  }
  const env = options.env ?? process.env
  mkdirSync(plan.home, { recursive: true })
  const listed = codexJson(['plugin', 'marketplace', 'list', '--json'], plan, env)
  if (!Array.isArray(listed?.marketplaces)) throw new Error('Codex marketplace list did not return a marketplaces array')
  const registered = listed.marketplaces.find((item) => item.name === plan.marketplace)
  if (registered) {
    if (typeof registered.root !== 'string' || !existsSync(registered.root) || realpathSync(registered.root) !== plan.root) {
      throw new Error(`Marketplace ${plan.marketplace} is registered at ${registered.root ?? '(unknown root)'}, not ${plan.root}. Refresh from the registered checkout or resolve that registration before refreshing.`)
    }
  }
  if (preparation) {
    console.log(`Preparing ${plan.marketplace} in ${plan.root}: ${preparation.command}`)
    // The shell receives only this fixed, allowlisted command. Repository paths
    // travel through cwd, and the package manager owns package-script execution.
    const result = spawnSync(preparation.command, { cwd: plan.root, env, shell: true, stdio: 'inherit', windowsHide: true })
    if (result.error || result.status !== 0) {
      throw new Error(`Plugin preparation failed (${result.status ?? result.signal ?? 'spawn'}): ${result.error?.message ?? preparation.command}`, { cause: result.error })
    }
    const preparedPlan = installationPlan(options)
    if (preparedPlan.marketplace !== plan.marketplace) throw new Error('Preparation changed the marketplace identity; refresh requires a stable marketplace')
    plan = preparedPlan
    if (!plan.plugins.length) {
      console.log(`No modified plugins for ${plan.home} after preparation.`)
      return plan
    }
  }
  if (!registered) {
    codexJson(['plugin', 'marketplace', 'add', plan.root, '--json'], plan, env)
  }
  // Codex stages fresh local bytes and atomically replaces even same-version installs.
  // All modules are already loaded; OPL can replace the cache containing this script.
  const trustFailures = []
  for (const plugin of plan.plugins) {
    const result = codexJson(['plugin', 'add', plugin.pluginId, '--json'], plan, env)
    if (typeof result?.installedPath !== 'string' || !existsSync(result.installedPath)) {
      throw new Error(`${plugin.name}: Codex install did not return a usable installedPath`)
    }
    plugin.installedPath = realpathSync(result.installedPath)
    console.log(`${plugin.name}: installed and enabled at ${plugin.installedPath}`)
    const reconciliation = reconcileOplAgents({
      name: plugin.name, installedPath: plugin.installedPath, home: plan.home, env,
    })
    if (reconciliation.reconciled) console.log('opl: reconciled agent registrations from the installed plugin.')
    const manifest = ['.codex-plugin/plugin.json']
      .map((path) => join(plugin.installedPath, path)).find(existsSync)
    const required = existsSync(join(plugin.installedPath, 'hooks', 'hooks.json')) || Boolean(manifest && readJson(manifest).hooks)
    try {
      const hooks = await ensurePluginHookTrust({
        repo: plan.root, home: plan.home, pluginId: plugin.pluginId,
        installedPath: plugin.installedPath, required, env,
      })
      if (hooks.length) console.log(`${plugin.name}: verified trust for ${hooks.length} installed hook(s).`)
    } catch (error) {
      trustFailures.push(`${plugin.pluginId}: ${error.message}`)
      console.error(`${plugin.name}: installed, but automatic hook trust failed: ${error.message}`)
    }
  }
  if (trustFailures.length) throw new Error(`Automatic hook trust failed for ${plan.home}: ${trustFailures.join('; ')}`)
  console.log('Refresh complete. Preparation runs only the repository-declared command; the installer adds no tests or skill evaluations. Start a new Codex session before using updated components.')
  return plan
}

export async function runInstallLocal(args = process.argv.slice(2)) {
  const { values } = parseArgs({ args, options: {
    repo: { type: 'string' },
    plugin: { type: 'string', multiple: true },
    'target-home': { type: 'string' },
    'local-only': { type: 'boolean' },
    'registered-source': { type: 'boolean' },
    'dry-run': { type: 'boolean' },
    help: { type: 'boolean', short: 'h' },
  } })
  if (values.help) {
    console.log('Usage: node install-local.mjs [--repo DIR] [--plugin NAME ... | --plugin all | --plugin modified] [--target-home ABSOLUTE_PATH] [--dry-run]')
    console.log('No --plugin selects source bundles changed from each installed copy. No --target-home refreshes existing user-level Windows and WSL homes. Use --plugin all explicitly for every plugin.')
    console.log('Authorized installs also trust and verify the selected plugins\' current hooks through Codex, without interactive onboarding.')
    console.log('A declared plugin:prepare-local package script runs before comparison and installation; preparation failure stops that home. Dry runs report preparation without executing it.')
    console.log('--dry-run validates local sources and prints the plan without invoking Codex or changing files; registrations are checked on installation.')
    console.log('Requires Node.js 22+ and Codex with plugin commands (verified with 0.151.0). CODEX_BIN can select a native executable or JS entrypoint.')
    return
  }
  if (values['target-home']) return installLocal({ repo: values.repo, plugins: values.plugin, targetHome: values['target-home'], dryRun: values['dry-run'] })
  return refreshUserHomes({ repo: values.repo, plugins: values.plugin, dryRun: values['dry-run'], localOnly: values['local-only'], useRegisteredSource: values['registered-source'] })
}

if (process.argv[1] && existsSync(process.argv[1]) && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await runInstallLocal() } catch (error) {
    console.error(`install-local: ${error.message}`)
    process.exitCode = 1
  }
}
