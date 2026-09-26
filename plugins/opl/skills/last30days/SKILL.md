---
name: last30days
description: Research what people have said about a topic in the last 30 days across Reddit, X, YouTube, TikTok, Hacker News, Polymarket, GitHub, and the web. Use for recent reactions, recommendations, comparisons, source-health checks, and configuration diagnosis; do not use for generic timeless web research.
---

# Last 30 Days

Run the bundled research engine and synthesize its evidence. Web research
improves planning, but it never substitutes for the engine.

## Locate this installation

Codex provides the selected skill's `SKILL.md` path. Set `SKILL_ROOT` to the
directory containing that exact file and use its sibling engine:

In PowerShell, set `$SKILL_ROOT` to that directory and use
`$ENGINE = Join-Path $SKILL_ROOT 'scripts/last30days.py'`; verify it
with `Test-Path -LiteralPath $ENGINE -PathType Leaf`. In POSIX, set
`SKILL_ROOT="<directory containing the selected SKILL.md>"`, use
`ENGINE="$SKILL_ROOT/scripts/last30days.py"`, and verify with
`test -f "$ENGINE"`. If the engine is missing, report the exact expected
path and stop.

Do not scan `~/.codex`, compare cache versions, search for another copy, or
substitute a repository checkout. The selected skill path is the authority;
this keeps instructions, scripts, and references from the same installation.

## Route the request

- If the user asks to configure sources, fix a source, inspect permissions, or
  diagnose configuration, read [references/setup-and-diagnostics.md](references/setup-and-diagnostics.md).
- If the user provided no topic, ask one short question for it and wait.
- Recognize `--days=N`, `--quick`, and `--deep` when the user supplies them.
- Classify the request as general/news, recommendations, or comparison.
  Comparisons include `X vs Y`, `X versus Y`, and direct compare requests.
- If the topic is too broad to retrieve meaningfully (for example a single
  common noun), ask for the angle before running anything. For demographic or
  numeric shopping queries, ask for relationship, interests, and budget rather
  than searching the literal age phrase.

## Resolve runtime capabilities

- A shell or command-execution tool is required. If it is unavailable, explain
  that the bundled engine cannot run and stop instead of returning web-only
  research under this skill's name.
- Read [references/search-planning.md](references/search-planning.md), then
  search the web for the current identity and query-planning facts it calls
  for. Do not name or require a particular search tool, MCP server, connector,
  or callable interface.
- For a blocking choice, ask the user one concise question and wait. Use a
  structured question interface when the host provides one, but do not require
  a particular tool.

## Resolve Python

The engine requires Python 3.12 or newer. Prefer
`LAST30DAYS_PYTHON` when set; otherwise select an installed interpreter
from `python3.14`, `python3.13`, `python3.12`, `python3`, or `python`. Assign the
verified choice to `LAST30DAYS_PYTHON` for every later command. Do not
install Python automatically.

Resolve candidates with `Get-Command` in PowerShell or `command -v` in a
POSIX shell. Prefer native `python` on Windows. Verify the selected executable
with `-c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"`.
Honor an explicit interpreter override instead of silently substituting another.
In PowerShell, store the verified path in `$env:LAST30DAYS_PYTHON` and
invoke it with `&`; in POSIX, use `LAST30DAYS_PYTHON` and quote it.
Resolve `ENGINE` to the bundled script using paths native to the active runtime.

If `LAST30DAYS_PYTHON` is still empty, report the requirement and stop.
Do not replace the engine with ordinary web search.

The default report directory is `~/Documents/Last30Days`. Honor
`LAST30DAYS_MEMORY_DIR` when the user or environment sets it.

## Check source health

Before research, run a cached doctor check. In PowerShell:

```powershell
& $env:LAST30DAYS_PYTHON -B -X utf8 $ENGINE doctor --cached --json
```

In POSIX:

```bash
"$LAST30DAYS_PYTHON" -B -X utf8 "$ENGINE" doctor --cached --json
```

Treat a source as usable only when its doctor record is `ready`, or `degraded`
with an active backend. Use the report's backend and prescription fields as
authoritative. Do not infer source availability from literal API-key names or
from one config file. If the user wants login-backed or optional sources that
are not usable, read the setup reference before research. If the requested
topic can be covered by the usable no-credential sources, state the actual
coverage and proceed unless the user asks to set up more.

When the request itself is a health check, run live `doctor --json`, report the
per-source status and exact prescriptions, and stop unless the user also asked
for research.

## Build and run the research command

Keep all arguments in a shell array so topics, paths, and apostrophes are not
reparsed by a nested shell. In PowerShell:

```powershell
$ReportDir = $env:LAST30DAYS_MEMORY_DIR
if (-not $ReportDir) { $ReportDir = Join-Path $HOME 'Documents/Last30Days' }
$EngineArgs = @($TOPIC, '--emit=compact', "--save-dir=$ReportDir")
```

In POSIX:

```bash
REPORT_DIR="${LAST30DAYS_MEMORY_DIR:-$HOME/Documents/Last30Days}"
ENGINE_ARGS=(
  "$TOPIC"
  --emit=compact
  --save-dir="$REPORT_DIR"
)
```

Append any user-requested depth/window flags. Follow
`references/search-planning.md`, write the generated JSON plan to a temporary
file, and append `--plan "$PLAN_FILE"` plus only the targeting flags actually
resolved. Use `--auto-resolve` only when the user explicitly requests the
engine's own resolution path; it is not a host-capability fallback.

For comparisons or recommendations, also read
[references/query-modes.md](references/query-modes.md) before invoking the
engine. General/news requests do not need that reference.

Run in the foreground with a timeout proportionate to depth (five minutes is a
reasonable default). Preserve stderr because it contains progress, saved-file
paths, degraded-source warnings, and comparison artifact locations.

In PowerShell, append flags with `$EngineArgs += @('--plan', $PLAN_FILE)` and
invoke `& $env:LAST30DAYS_PYTHON -B -X utf8 $ENGINE @EngineArgs`.
In POSIX, append with `ENGINE_ARGS+=(--plan "$PLAN_FILE")` and invoke
`"$LAST30DAYS_PYTHON" -B -X utf8 "$ENGINE" "${ENGINE_ARGS[@]}"`.

If the engine asks a clarifying question or refuses a low-quality query,
surface that question and wait. If it fails, report the concrete failure and
the relevant doctor prescription. Do not mask a failed engine with a separate
web-only answer.

## Synthesize

After the engine completes, read
[references/synthesis.md](references/synthesis.md). Use the entire compact
output, including evidence clusters, community comments, uncertainty markers,
source coverage, and the engine-reported saved paths.

The final response must:

- distinguish evidence from inference;
- cite only URLs present in engine output or fetched during this run;
- reflect actual source coverage and uncertainty;
- include the engine-reported raw artifact path when one was saved; and
- omit engine scratchpad, planner JSON, internal scoring tuples, and
  secrets.

Do not add a generated version badge. Runtime version reporting, when needed by
diagnostics, is owned by the executable and its nearest `.codex-plugin/plugin.json`.

## Follow-ups

Answer follow-up questions from the completed research while it remains current
for the user's requested window. Run new research when the user changes the
topic, changes the time window, requests a refresh, or asks for evidence the
existing report did not collect.
