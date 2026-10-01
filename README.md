# OPL

One-Person Labs developer tooling for Codex: skills, specialist agents, shared instructions, and workflow hooks.

## Install

```sh
codex plugin marketplace add https://github.com/OnePersonLabs/opl
codex plugin add opl@opl
```

Start a new Codex task after installation. Invoke skills with `$opl:<skill-name>`, such as `$opl:review-changes`, `$opl:debug`, or `$opl:adhd`.

## Develop

Use Node.js 24 or later, Python 3, Git, and the Codex CLI.
Hooks require Python 3.11 or later. Research workflows require Python 3.12 or later.

```sh
npm ci
npm run verify
npm run test:installed -- --plugin opl
```

Shipping files live in `plugins/opl/`. Tests and fixtures live in `tests/`. Repository commands live in `tools/`.

Instruction baseline recovery uses local history first. Remote recovery uses the original OnePersonLabs plugin repository for revisions below 10 and this repository for revisions 10 and later.

When the user authorizes tests, run a focused test for the affected behavior:

```sh
npm run test:focus -- --file tests/unit/opl/codex-hooks.test.mjs
```

Review skill instructions and activation metadata against their sources and structure after changes. `npm run release:verify` runs deterministic checks and an installed-copy checkpoint.

The installed-copy checkpoint uses a separate Codex home, compares the installed files with source, and verifies hook trust. To refresh OPL in your existing Codex home:

```sh
npm run install:local -- --plugin opl
```

## Imported skill updates

Imported skills record their source, directory commit and tree hash, local fixes,
and last check attempt in `references/UPDATE.md`. Before a commit, OPL lists these
manifests and checks entries that are at least 48 hours old. Due checks use
`gpt-6-luna` with medium reasoning for adaptation and a separate review. They
require network access and can consume model usage.
Child runs ignore user configuration while retaining the normal authentication
home. Windows child runs use the unelevated sandbox.

`VERSION` records the latest commit affecting the upstream skill directory and
that directory's tree hash. `SKILL SOURCE` is its current GitHub directory URL;
this updater does not accept individual file URLs. `MANAGED FILES` separates
upstream files from local additions. `CHECK STATUS` distinguishes successful,
pending, and failed attempts.

The updater preserves local resources and replaces upstream package files at a
verified source revision. It stages reviewed changes in the active commit index.
The existing instruction-version check runs next. Recent successful checks skip
the update step. The pre-push hook runs the existing repository checks.

Due skill packages must contain clean, tracked files. Staged or partial changes
in a due package block maintenance before any remote request. Unrelated staged
and working-tree changes remain in place. Due updates also require an ordinary
commit using the standard index. If a partial or custom-index commit is blocked,
stage the intended changes with `git add`, then use `git commit` without path
arguments or a custom `GIT_INDEX_FILE`. Fresh successful checks permit partial
commits because they do not change files. A failed check blocks the commit and
retains its evidence directory and failure receipt for investigation. Checks are
limited to one automatic attempt per 48 hours, including failed attempts. Read
the reported error before retrying. The pre-commit hook runs
`node tools/check-imported-skill-updates.mjs` separately from the instruction-version
checker.

## License

OPL is MIT licensed. Bundled third-party code retains its own license notices.
