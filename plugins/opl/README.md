# OPL

One-Person Labs skills, specialist agents, shared instructions, integrations, and workflow hooks for Codex.

## Runtime

Hooks use Python 3.11 or later and the standard library. Native Windows uses `python`; POSIX uses `python3`. Research through `$opl:last30days` requires Python 3.12 or later. Provider discovery through an npm Codex launcher also requires Node.js. GitHub issue verification requires `gh`.

Install the browser and retrieval tools used by the relevant workflows:

```sh
npm install -g agent-browser chrome-devtools-cli fetch-cli
agent-browser install
```

On Linux, use `agent-browser install --with-deps` to install Chromium system dependencies.

## Skills

Invoke a skill with `$opl:<skill-name>`. Common starting points:

| Skill | Purpose |
| --- | --- |
| [$opl:review-changes](skills/review-changes/SKILL.md) | Review a concrete patch. |
| [$opl:debug](skills/debug/SKILL.md) | Investigate and reproduce a failure. |
| [$opl:test-driven-development](skills/test-driven-development/SKILL.md) | Verify behavior through realistic tests. |
| [$opl:adhd](skills/adhd/SKILL.md) | Preserve task state and keep one active path. |
| [$opl:configure-harness](skills/configure-harness/SKILL.md) | Compare capabilities and review a deliberate setup. |
| [$opl:update-instructions](skills/update-instructions/SKILL.md) | Replace outdated global instructions after one approval, keeping a dated backup. |
| [$opl:handoff](skills/handoff/SKILL.md) | Prepare a resumable task handoff. |
| [$opl:long-command-wakeup](skills/long-command-wakeup/SKILL.md) | Run a long command and queue a bounded continuation. |
| [$opl:refresh-local-plugins](skills/refresh-local-plugins/SKILL.md) | Refresh selected local plugins and verify hook trust. |

All shipped skills are in [skills/](skills/).

## Instructions and agents

The instruction context hook compares the installed instruction revision with the user's recorded version. Use `$opl:update-instructions` to replace outdated instructions after one approval. It saves the previous file byte for byte in a dated backup; custom rules are not merged.

OPL ships task worker, grunt worker, reviewer, QA, explorer, and documentation researcher roles in [agents/](agents/). Local installation reconciles their `opl-` role registrations with the installed paths.

## Compatibility and discipline

The [compatibility guide](compatibility/README.md) defines optional repository policy in `.opl/config.json` and shipped conflict rules. Hooks check enabled providers and report policy violations.

Deferrals that cite GitHub Issues are verified through `gh`. Every referenced issue must exist and remain open before the deferral is accepted.

## Task watchdog

The lifecycle observer records local task activity in `$CODEX_HOME/codex-watch/state.sqlite3`. To send a notification after 25 minutes without activity, set `CODEX_WATCH_NTFY_URL` to an HTTPS ntfy topic and optionally set `CODEX_WATCH_NTFY_TOKEN`. Then run:

```sh
npm run codex-watch -- run
```

From an installed plugin, run `python <plugin-root>/scripts/codex-task-watch.py run` (`python3` on POSIX). Notifications include the last completed assistant response; use an access-controlled topic when this text is private. The script also supports `status --json`, `test-notification`, and `prune --older-than 30d`.
