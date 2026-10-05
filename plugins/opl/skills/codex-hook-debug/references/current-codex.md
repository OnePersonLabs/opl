# Current Codex contracts and sources

Checked on 2026-09-27 against official web guidance and a local Codex CLI 0.157.0. This is a debugging baseline, not a compatibility promise for every Codex surface or version. Recheck the affected binary and relevant documentation slice when behavior differs.

## Official sources

- [Codex hooks](https://developers.openai.com/codex/hooks/) -- discovery, trust, events, handler types, matchers, input/output, Windows commands, managed hooks, and asynchronous execution. At the check date, this URL redirects to [Hooks on ChatGPT Learn](https://learn.chatgpt.com/docs/hooks).
- [Configuration reference](https://developers.openai.com/codex/config-reference/) -- effective hook feature and state settings, logging, and managed restrictions.
- [Configuration basics](https://developers.openai.com/codex/config-basic/) -- config layers, user home, and trusted project configuration.
- [Build plugins](https://developers.openai.com/codex/plugins/build/) -- plugin manifests, installed roots, and bundled hook discovery.
- [App-server protocol](https://developers.openai.com/codex/app-server/) -- initialization and version-specific protocol discovery. Use the installed binary's schema for `hooks/list` availability and fields.
- [Official Codex repository](https://github.com/openai/codex) -- implementation and tests when docs leave a material gap. Inspect the release matching the affected binary. Use local source or `gh` for bounded code reads when available.
- [Codex 0.157.0 command runner](https://github.com/openai/codex/blob/rust-v0.157.0/codex-rs/hooks/src/engine/command_runner.rs) -- version-matched shell selection, input, working directory, and process output capture.
- [Codex 0.157.0 hook dispatcher](https://github.com/openai/codex/blob/rust-v0.157.0/codex-rs/hooks/src/engine/dispatcher.rs) -- matching-handler execution. Check another release's source when investigating another binary.

Prefer these sources over old posts that describe hooks as universally experimental, unsupported on Windows, or limited to a few events. Do not import Claude Code behavior without checking Codex's actual contract.

## Contracts that change the diagnosis

**Discovery and trust.** Active user/repo config layers can contain `hooks.json` or inline `[hooks]`. Sources load together. Project config requires project trust; non-managed hooks also require review of the current definition. Managed policy can force hooks on or off or restrict execution to managed hooks. Current feature configuration uses `[features].hooks`; `codex_hooks` is a deprecated alias. Check existing version compatibility before renaming it.

**Plugin ownership.** The default bundled file is `hooks/hooks.json`. A `.codex-plugin/plugin.json` `hooks` entry can provide paths, arrays, or inline definitions and overrides default discovery. Hook file paths must remain inside the plugin root. Plugin hooks use the same event and trust model as other non-managed hooks.

**Execution.** Commands run from the session cwd. `timeout` is seconds; the documented default for most command hooks is 600 seconds. `SessionEnd` and `Interrupt` default to one second and permit up to three seconds. JSON uses `commandWindows`; inline TOML accepts `command_windows` or `commandWindows`. The 0.157.0 runner selects `COMSPEC` or `cmd.exe` with `/C` on native Windows. On other platforms, it selects `SHELL` or `/bin/sh` with `-lc`. Check the selected environment value before choosing command syntax. Matching command handlers can run concurrently; one block does not prevent another matching handler from starting.

**Handlers.** Current docs support `command` and `mcp_tool`. `prompt` and `agent` handler forms are parsed but skipped. MCP hooks run synchronously on an existing connection. They do not request tool approval or trigger other hooks. MCP errors and missing connections do not block the original action, and `SessionEnd` does not support MCP hooks. Check the installed release before relying on these capabilities.

**Matcher domains.** Matchers are regex strings. Omitted, empty, or `"*"` matchers match every occurrence of supported events. Use the domain for the actual event:

| Event | Matcher input |
| --- | --- |
| `PreToolUse`, `PostToolUse`, `PermissionRequest` | Tool name. Verify captured names and documented aliases for `apply_patch`, `Edit`, and `Write`. |
| `SessionStart` | `startup`, `resume`, `clear`, or `compact`. |
| `PreCompact`, `PostCompact` | `manual` or `auto`. |
| `SubagentStart`, `SubagentStop` | Subagent type. |
| `SessionEnd` | End reason; currently `other`. |
| `UserPromptSubmit`, `Stop`, `Interrupt` | Matcher is ignored. |

**Event payload and output.** Use the current event's documented JSON input. Common fields include `session_id`, `transcript_path`, `cwd`, `hook_event_name`, and `permission_mode`. Verify their presence and event extensions for the affected version. Do not synthesize a Bash-shaped payload for every tool. Plain stdout is accepted for some context events; other events require structured JSON when they return output. Exit `0` with no output is a valid success. Exit `2` can be a policy decision rather than a crash. Error behavior and decision fields depend on the event. Review the relevant event section before changing output or exit codes.

**Continuation and completed actions.** A `Stop` block requests another model continuation. `PostToolUse` feedback occurs after the tool ran and cannot roll back its effects. A generic message that says a hook failed does not establish whether an action ran, was blocked, or will repeat. Correlate the event and action records before retrying.

## Local assurance and limits

A read-only initialized `hooks/list` query on Codex 0.157.0 returned hooks from two enabled plugins, their installed source paths, current hashes, enabled states, and trust states without discovery errors or warnings. This verifies that runtime source attribution is available in that binary. It does not prove event execution, every handler type, another surface's active configuration, or behavior on an older release.

The query did not establish the affected process's selected shell or inherited environment. The pinned runner source establishes the default selection rules above. Inspect the process environment when it affects a diagnosis. Official sources document user/repository discovery. The plugin-only observation does not replace a check of those layers in the affected session.
