import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const python = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3')
const script = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'plugins', 'opl', 'scripts', 'codex-task-watch.py')
const result = spawnSync(python, ['-B', '-X', 'utf8', script, ...process.argv.slice(2)], {
  stdio: 'inherit',
})

if (result.error) {
  console.error(`codex-watch: could not launch Python: ${result.error.message}`)
  process.exitCode = 1
} else {
  process.exitCode = result.status ?? 1
}
