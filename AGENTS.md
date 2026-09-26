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

After each executable behavior edit, run the smallest finite focused test that
can prove the behavior. After it passes, run the deterministic suite for only
the affected plugin:

```bash
npm run test:contract -- --plugin <plugin-name>
npm run test:unit -- --plugin <plugin-name>
```

Cross capability boundaries only when the change crosses them:

- Skill instructions or activation metadata: run
  `npm run eval:smoke -- --plugin <plugin-name> --skill <skill-name>`.
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

The full skill corpus is not a routine update check. Only the explicit
`npm run release:verify` release gate runs clean installed checks for every
plugin and behavioral evaluations for every shipped skill. `npm run verify`
runs the complete deterministic repository gate without model evaluations.

Do not add timestamp cachebusters to plugin versions and do not restore the
retired all-plugin reinstall script. Codex's installed cache is tested only at
the black-box checkpoint or used by the explicit installation command.
