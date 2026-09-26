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

Run a focused test after a behavior change:

```sh
npm run test:focus -- --file tests/unit/opl/codex-hooks.test.mjs
```

Use `npm run eval:smoke -- --plugin opl --skill <skill-name>` after changing skill instructions or activation metadata. `npm run release:verify` runs deterministic checks, an installed-copy checkpoint, and all retained skill evaluations. Evaluations use Codex and can consume model usage.

The installed-copy checkpoint uses a separate Codex home, compares the installed files with source, and verifies hook trust. To refresh OPL in your existing Codex home:

```sh
npm run install:local -- --plugin opl
```

## License

OPL is MIT licensed. Bundled third-party code retains its own license notices.
