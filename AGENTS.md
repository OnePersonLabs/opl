# Repository Instructions

## Local plugin development

This repository uses the source-first workflow in `README.md`. The plugin root
under `plugins/opl/` contains only shipping files. Tests live under `tests/`.
Repository drivers live under `tools/`.

OPL's `plugins/opl/AGENTS.md` has an independent positive integer instruction
revision in its `opl-instructions-version` marker. Increment and stage that
revision whenever changing instruction content. The pre-commit hook compares
the staged file with `HEAD` and rejects changed content without a staged bump;
an unstaged bump does not satisfy the check. Initial version adoption uses 1
in an existing repository. The first standalone commit preserves the inherited
revision 10.

## Human-collaboration service during a local plugin refresh

Before refreshing a local plugin, use `$opl:human-collaboration`'s
`pause-for-refresh` operation from the workspace being refreshed. It checks
authenticated readiness, records whether the service was running and its bind
settings, and stops it gracefully only when it was running. The operation must
confirm both listener shutdown and process exit; an unresponsive live service
blocks refresh. Do not run separate repeated service checks. Continue only when
the operation reports the service stopped or not running.

After the refresh attempt, use the installed `$opl:human-collaboration` skill's
`resume-after-refresh` operation from the same workspace, even if the installer
failed. It starts the service only when the pause record says it was running.
If the installed helper is unavailable because refresh failed, use the source
skill to resume it. A failed restart keeps the record for retry; report the
failure and do not clear it. When the service restarts, open and report the new
pairing URL returned by the operation.

## After a local plugin refresh

After a successful `$opl:refresh-local-plugins` refresh, run the OPL checks used
at session startup. Check configuration and global instructions in each refreshed
user-level Codex home. The user has approved the update question: apply required
OPL agent TOML configuration and documented defaults with the installed
`scripts/codex-config-check.py fix`, and update outdated global instructions with
`$opl:update-instructions`. Do not ask for that approval again.

Keep the safety checks and dated backups from the update helpers. Do not downgrade.
If homes share an instruction file, update its resolved target once. After a
global-instruction replacement, restore this user-requested post-refresh rule in
the user-level file. Keep the rule in this repository's `AGENTS.md` and the
user-level file; do not add it to `plugins/opl/AGENTS.md`.

## Tests

Keep test output quiet on success; report only a brief pass summary or nothing.
On failure, report errors and relevant diagnostics.

Do not add tests for skill invocation. Do not add tests that consume AI tokens
without explicit permission. If tests are required to prove new behavior or
validate significant modifications, one-time smoke tests are allowed. Batch and
defer all tests that require AI usage until the end of the root agent's turn.
Use as few subagent or `codex exec` prompt batches as possible. Group tests by
model and effort level. For each batch, use the minimum model and effort level
that you believe is required.

During executable changes, run focused checks when they resolve an implementation
decision or reproduced failure. At a coherent integration checkpoint, batch the
deterministic suites for the affected plugin. Reuse results while their relevant
inputs remain unchanged; do not rerun both suites after each intermediate edit:

```bash
npm run test:contract -- --plugin <plugin-name>
npm run test:unit -- --plugin <plugin-name>
```

Cross capability boundaries only when the change crosses them:

- Skill instructions or activation metadata: review the changed package and
  validate its structure. Apply the AI test permission and batching rules above
  if a one-time behavioral smoke test is needed. Do not add invocation tests.
- MCP launcher or server metadata: run
  `npm run test:mcp -- --plugin <plugin-name>`.
- UI code or resources: run `npm run test:ui -- --plugin <plugin-name>`.
- Package-visible files at a coherent checkpoint: run
  `npm run test:installed -- --plugin <plugin-name>`.

`test:installed` uses a persistent, separate black-box Codex home for each
selected plugin. After comparing the installed files to source, it uses
Codex's app-server API to trust that plugin's current hook hashes and verify
their trusted status. This is an automated checkpoint: do not open a terminal
or require sign-in, sandbox onboarding, or a manual `/hooks` confirmation.
Surface discovery or trust failures instead of skipping them.

`npm run install:local -- --plugin <plugin-name>` is an
installation-only consumer operation. It never runs unit tests, contract
checks, installed checks, or skill evaluations. An authorized local refresh
also trusts the selected installed plugins' current hooks through the shared
installer; leave unrelated hooks and sandbox settings unchanged. Use
`--plugin all` only when the user explicitly asks to install every marketplace
plugin. For a normal `$opl:refresh-local-plugins` invocation, use the current
user's existing default Codex home or homes without asking for a path. Use an
explicit `--target-home` when the user names a home or the task clearly targets
one, including isolated tests.

The full skill corpus is not a routine update check. The explicit
`npm run release:verify` release gate runs clean installed checks for every
plugin. AI evaluations require explicit permission and follow the batching rules
above; a release gate does not automatically authorize them. `npm run verify`
runs the complete deterministic repository gate without model evaluations.

Do not add timestamp cachebusters to plugin versions and do not restore the
retired all-plugin reinstall script. Codex's installed cache is tested only at
the black-box checkpoint or used by the explicit installation command.
