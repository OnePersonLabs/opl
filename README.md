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
python -m pip install playwright
npm run verify
npm run test:installed -- --plugin opl
```

The pre-push hook runs the deterministic checks, including real-browser UI tests.
Install Playwright in the Python environment used by the checks (`PYTHON_BIN`
selects a different interpreter). The UI tests use an installed Chromium browser.
To install Playwright's development browser, run `python -m playwright install chromium`.
Set `OPL_CHROMIUM_BIN` when you need a specific browser executable.
The checks report missing prerequisites and do not install them automatically.

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

## License

OPL is MIT licensed. Bundled third-party code retains its own license notices.
