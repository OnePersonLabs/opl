---
name: refresh-local-plugins
description: Refresh locally modified Codex plugins in existing user-level Windows and WSL Codex homes. Use after local edits or pulls, for stale installed copies, or to preview a refresh. For isolated tests, pass --target-home "<absolute-path>"; not for publishing.
---

# Refresh Local Plugins

Prepare and refresh changed shipping bundles from the source checkout through
Codex's native installer. The bundled helper works across local marketplace
repositories; shipping-source checkouts need no build setup.

## Select source and destinations

Resolve the source checkout from the request and session context. Run the helper
from this **loaded skill's actual directory**, including when this skill is in
Codex's installed cache. Never use the installed cache as the source checkout.

By default, refresh every marketplace plugin whose source bundle differs from
the installed copy in each destination. This comparison is per Codex home, so
it catches committed changes after a pull as well as uncommitted edits. Do not
select every marketplace plugin unless the user explicitly asks for all. Honor
explicit plugin selections when supplied.

The helper handles the native user-level `~/.codex` and the other accessible
Windows or WSL user-level `~/.codex` in one invocation. It translates paths
between environments as needed, uses each environment's registered checkout
for that marketplace, and invokes its normal `node` and Codex CLI. It skips
missing homes and reports unavailable environments. Do not ask
the user to specify a target home for a normal refresh or substitute
`CODEX_HOME`, an isolated test home, or another profile.

Keep discovery and preview requests read-only: use `--dry-run`, which checks
both accessible homes without installing.

## Run the bundled helper

Use `--repo` when the checkout is not the current directory. No `--plugin` and
no `--target-home` refreshes modified plugins in both existing user-level homes:

```text
node <loaded-skill-directory>/scripts/install-local.mjs --repo <source-checkout>
```

Repeat `--plugin <name>` for explicitly selected plugins. Use `--plugin all`
alone only for an explicit whole-marketplace request. `--dry-run` prints the
per-home plan without mutation. `CODEX_BIN` can select a native Codex executable
or JavaScript entrypoint. The helper retains `--target-home` for isolated tests
and explicit exceptional requests; a normal skill invocation does not use it.

The helper validates selected sources and existing marketplace registration
before installation. A same-name marketplace pointing elsewhere is a conflict,
not permission to rebind it; report the conflict for that environment.

If the checkout declares `scripts["plugin:prepare-local"]` in `package.json`,
the helper runs that script with the declared package manager (npm by default)
before comparing bundles with installed copies. That command owns compilation
and bundle assembly. Preparation failure stops installation for that home;
never substitute an older bundle. Each host prepares its registered checkout.
Repositories without this script install their shipping sources directly.
`--dry-run` never builds: it reports required preparation and marks plugin
selection pending when a build is needed. Use the helper for the whole refresh;
do not separately run the preparation command first.

The helper calls native `codex plugin add` to atomically refresh and enable
each selected plugin, including unchanged versions. Do not add uninstall steps,
version cachebusters, or verification commands. Run tests separately only when
requested or required by a development task.

## Hook trust and handoff

An authorized refresh also authorizes trusting the refreshed plugins' current
installed hooks in each environment. The helper uses that environment's Codex
app-server API to save only selected hook hashes and verify trusted status. It
preserves unrelated hooks and sandbox settings. A hook trust failure does not
stop later selected plugins from refreshing. Do not ask for sign-in, sandbox
setup, or manual hook approval when automatic trust succeeds.

If automatic hook trust fails in either environment, finish the other reachable
refreshes, then tell the user exactly which environment(s) and plugin(s) need
manual trust. Ask them to open a fresh Codex session in each affected
environment, review and trust those plugin hooks with `/hooks`, and reply
`done`. Wait for that reply before treating the refresh as complete. Do not
claim hook trust was verified for an affected environment until it has been
checked again after the reply.

## Report the result

Report refreshed plugin IDs and installed paths by environment, or the
preflight result. Surface failures with completed progress. Tell the user to
start a fresh Codex session to load updated components. Installation and trust
verification do not prove that plugin tests pass or hooks execute correctly.
