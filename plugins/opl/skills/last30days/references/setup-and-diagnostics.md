# Setup and diagnostics

Read this reference only for setup, source-health, missing-source, credential,
or permission questions, or when the pre-research doctor check shows that the
user wants coverage that is not configured.

Use `ENGINE` and `LAST30DAYS_PYTHON` resolved by `SKILL.md`.

## Inspect before changing anything

Run the safe permission preflight first:

```bash
"$LAST30DAYS_PYTHON" "$ENGINE" --preflight
```

It reports the config source, ignored project config, planned cookie mode,
planned local writes, optional commands, endpoint overrides, and available
sources without reading browser-cookie values, writing configuration, or
running research.

For a source-health request, run:

```bash
"$LAST30DAYS_PYTHON" "$ENGINE" doctor --json
```

Report each requested source's tier, status, prescription, and active backend
when that source uses a backend chain. Do not translate an unavailable optional
source into a failure of sources that work independently.

## Configuration locations

The curated skill has its own namespace and does not read the upstream skill's
configuration:

- Global: `~/.config/last30days/.env`
- Project: `.agents/last30days.env`, discovered from the working
  directory up to the repository root
- Project trust gate: `LAST30DAYS_TRUST_PROJECT_CONFIG=1` must come
  from the process environment or global config; a project file cannot trust
  itself
- macOS Keychain services: `last30days-<KEY>`
- `pass` entries: `last30days/<KEY>` by default

Process environment values have highest priority, followed by a trusted
project file, global config, Keychain, and `pass`.

Never copy values from `~/.config/last30days`, `.agents/last30days.env`, or
another installed skill. If the user wants to migrate credentials, explain the
two namespaces and ask before copying any secret.

## Configure a missing source

The engine does not install dependencies, register accounts, or acquire API
keys. Use the source's own documented installation or signup flow, then place
only the required setting in the curated config or credential store. Explain
every planned local change and obtain consent before making it.

For browser-backed X access, ask which logged-in browser the user authorizes
the engine to read. Set `LAST30DAYS_FROM_BROWSER` to that browser only;
never use `auto` unless the user explicitly authorizes probing every supported
browser. Browser-cookie values must not appear in tool output or reports.

Re-run `--preflight` and live `doctor --json` after a change. A source is active
only when doctor reports it ready or degraded with a usable backend.

## Optional sources

Do not upsell optional providers during ordinary research. Configure one when
the user requests the corresponding coverage or a doctor prescription calls
for it:

- `SCRAPECREATORS_API_KEY`: TikTok plus Reddit and YouTube fallback coverage
- `XAI_API_KEY`, `AUTH_TOKEN` + `CT0`, or an authenticated supported X CLI: X
- `BRAVE_API_KEY`, `EXA_API_KEY`, `SERPER_API_KEY`, or `PARALLEL_API_KEY`:
  engine-side web discovery
- `GITHUB_TOKEN`: raises GitHub API rate limits; public GitHub search remains
  available without it

Provider credentials are independent. Never use Codex or ChatGPT login state
as an API credential, share keys between providers, print secrets, or include
them in report artifacts.

When manually updating the global `.env`, create it with user-only permissions
and append or replace only the requested key. Never truncate the file:

```bash
mkdir -p "$HOME/.config/last30days"
chmod 700 "$HOME/.config/last30days"
touch "$HOME/.config/last30days/.env"
chmod 600 "$HOME/.config/last30days/.env"
```

Do not put a raw secret in a shell command or tool output. Prefer a secure
credential store or a user-performed edit.

## Permission boundary

The skill may read public platform data, invoke local helper commands, access
browser cookies after consent, call configured provider endpoints, and save
local reports. It does not post, like, message, or modify content on researched
platforms. Publishing, uploading, or sending a report is outside this skill's
research capability and requires a separate explicit user request and an
appropriate tool.
