---
name: codex-hook-debug
description: Diagnose and fix Codex lifecycle hook errors, missing executions, unexpected blocks, and repeated continuations across any installed plugin, user CODEX_HOME, and repository .codex configuration. Use for hook discovery, trust, matching, runtime, and output-contract failures; not Git hooks or React hooks.
---

# Codex Hook Debug

Trace the reported behavior to the active hook definition and its execution. Preserve the hook's intended policy while fixing the cause. Do not assume that the failing hook belongs to the current repository or a particular plugin.

## Establish the runtime and source

Record the exact error, event, triggering action, timestamp, session working directory, host OS, Codex surface, and executable version. Record launch and config overrides that affect hook execution. Resolve the affected process's `CODEX_HOME`; use its default home only when no override exists. A desktop app, CLI, remote host, and WSL process can use different binaries, homes, paths, and environments.

Inspect each applicable source:

| Source | Inspect |
| --- | --- |
| User | `CODEX_HOME/hooks.json` and inline `[hooks]` in `CODEX_HOME/config.toml`. The usual home is `~/.codex`. |
| Repository | `.codex/hooks.json` and `.codex/config.toml` in active project config layers. Check the actual worktree and session subdirectory. |
| Installed plugins | Every relevant enabled plugin's installed root, `.codex-plugin/plugin.json`, manifest `hooks` entries, and default `hooks/hooks.json` when no override is present. |
| Other active layers | Session overrides and managed/system requirements when discovery or effective configuration identifies them. |

Hooks from multiple sources are additive. Higher configuration precedence does not replace lower-layer hook definitions. A layer can merge both JSON and inline TOML with a warning. Do not assume that the first command match is the only handler or that the hook file's directory is the command's working directory.

Use `/hooks` in a supported CLI or the affected runtime's read-only `hooks/list` app-server API to establish loaded definitions. An app-server client must initialize the protocol before listing hooks. Inspect returned errors and warnings, then map the failing handler by event, matcher, command or MCP tool, source path, and plugin identity. Keep its key, current hash, enabled state, managed status, and trust status when available. Preserve multiple candidates until evidence identifies the owner. File inspection alone does not prove that Codex loaded a hook.

Under normal trust enforcement, non-managed hooks with untrusted or modified definitions are listed but skipped until trusted. Check for an existing authorized trust-bypass invocation before concluding that such a handler could not run. Concurrent execution applies to eligible handlers, not every listed definition.

Read [references/diagnosis.md](references/diagnosis.md) for the relevant failure class. Read [references/current-codex.md](references/current-codex.md) when event semantics, feature names, platform behavior, or documentation freshness could change the diagnosis.

## Diagnose before editing

Separate these failure classes:

- **Discovery:** Invalid config, an inactive project layer, a disabled plugin or feature, a manifest override, or the wrong home, host, or installed version.
- **Eligibility:** A disabled hook, an untrusted or modified definition, managed policy, or an event/matcher that does not apply to the action.
- **Execution:** A missing executable or file, shell quoting, working-directory assumptions, environment differences, stdin handling, timeout, or a script exception.
- **Output contract:** Invalid or inappropriate event output, diagnostic text on stdout, a mismatched `hookEventName`, or an unsupported decision field.
- **Policy or lifecycle:** An intentional rejection, duplicate handlers, or a `Stop`/`SubagentStop` continuation that repeats without progress.

Read the definition and called implementation before executing a replay. A trusted definition is not evidence that the script is correct. A nonzero exit is not sufficient evidence that the hook crashed. A successful direct script run is not proof that Codex discovers, trusts, matches, and accepts its output.

For command hooks, reproduce with the selected platform command, actual cwd, required environment, and a sanitized representative event JSON on stdin. Close stdin after the payload. Capture stdout, stderr, exit status, and elapsed time separately. Bound the run to the relevant timeout. Review side effects first; use an isolated fixture or dry-run mode when the real payload would perform an unauthorized action.

For MCP hooks, inspect the existing server connection, tool availability, expanded argument types, returned result, and timeout. Do not translate a connection failure into a shell-command repair.

If the evidence shows an intentional rule block, explain the rule and the triggering input. Complete compliant independent work. Follow applicable authorization and conflict rules before changing or bypassing that policy. The skill invocation does not authorize global hook disabling, trust bypass flags, approval decisions, bulk trust writes, or changes to managed requirements. Reuse existing authorization when it covers the specific action.

## Fix and verify the owning layer

Make the smallest change that fixes the established cause. Preserve unrelated hooks, sandbox settings, and policy outcomes. Do not mask errors with empty success output, broad exception suppression, unconditional allow decisions, or arbitrary timeout increases.

For a plugin hook, identify both the installed copy used by Codex and its maintained source. Prefer a durable source fix and the plugin's supported targeted refresh when authorized. Do not treat edits to a cache copy as a durable release fix, refresh every plugin, or invent a local source for a third-party plugin. If only the installed copy is available, report that limitation and the supported update or upstream repair route.

Recheck discovery and eligibility after config or installation changes. If the definition hash changed, use the supported review/trust flow within existing authorization, or report the specific approval still needed. Reload only the affected runtime when required. Do not assume an existing session has adopted changed definitions.

Verify the corrected handler with the relevant fixture, then check the original event through Codex with a safe, authorized trigger. For policy hooks, check a compliant case and the applicable rejection case. For repeated continuations, check that the event can finish after its condition is satisfied. Run the owner's required checks when editing maintained code. Distinguish script replay, runtime discovery, and actual event verification in the result; identify any missing check.

Report the root cause and evidence, active source and maintained source, change made, checks completed, and remaining approval or runtime limitation. Redact secrets and unnecessary prompt or transcript content from shared evidence.
