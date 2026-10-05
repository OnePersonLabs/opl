# Diagnose the failure class

Read only the sections that explain the observed symptom. Use the current runtime's schema and evidence when they differ from examples here.

## The hook is missing or does not fire

| Evidence | Next check |
| --- | --- |
| The file exists, but discovery has no corresponding handler | Confirm the affected binary/home/cwd and active config layers. Inspect discovery errors before editing the script. |
| Repository hooks are absent | Check project trust and the active `.codex` layer in the current worktree. User and system hooks can still load in an untrusted project. |
| Plugin hooks are absent | Confirm the plugin is enabled and identify its installed root. A manifest `hooks` entry overrides default-file discovery. Validate manifest paths against that root. |
| A loaded handler is disabled or needs review | Check its own enabled state and definition hash. Under normal trust enforcement, untrusted or modified non-managed definitions are skipped. Check existing launch overrides when eligibility is uncertain. Project trust and hook trust are separate. |
| Only managed hooks appear | Check effective `allow_managed_hooks_only` and managed feature requirements. Treat a policy restriction as a policy issue, not a missing file. |
| An event never matches | Compare the captured event/tool name with the event-specific matcher contract. Verify regex syntax and event support in the installed version. |
| A handler is parsed but skipped | Verify handler-type support. Do not assume a Claude-compatible config shape makes every Claude hook capability executable in Codex. |

Inspect all applicable sources before attributing a failure to one plugin. Equivalent commands can be registered in user config, repo config, multiple enabled plugins, or both JSON and TOML in the same layer. Compare loaded identities and event traces; do not assume config precedence removes duplicates.

Eligible matching command handlers can start concurrently. Do not rely on file order or a rejecting handler to prevent another eligible handler's side effects. A listed handler that is skipped for trust does not enter that execution set.

For an app-server investigation, use the current method schema. The installed Codex 0.157.0 supports an initialized `hooks/list` request with `{"cwds":["<absolute-session-directory>"]}`. Its result contains workspace entries under `data`, each with `cwd`, `hooks`, `errors`, and `warnings`. Useful handler fields include `key`, `eventName`, `handlerType`, `command`, `matcher`, `sourcePath`, `source`, `pluginId`, `enabled`, `isManaged`, `currentHash`, and `trustStatus`. API event names can use camelCase while config event names use PascalCase. Preserve the returned values; verify schema availability in other versions.

## A command cannot start, crashes, or times out

Resolve the exact platform command from its active definition. Check these dependencies before replacing it:

- The interpreter and required libraries must be available to the Codex process. An interactive shell's PATH, virtual environment, or shell profile can differ from the app's environment.
- Check the shell that actually executes the hook. PowerShell, `cmd.exe`, POSIX shells, Git Bash, and WSL have different quoting, environment-variable syntax, path rules, and executable lookup. The shell used by a Codex tool is not proof of the hook runner's shell.
- On native Windows, inspect `commandWindows`. On WSL, inspect the Linux command and Linux paths. Do not pass a Windows path directly to a Linux interpreter or assume `python3` and `python` name the same runtime.
- Hook commands use the session cwd. Test a repository started from a subdirectory when relative script paths are suspect. Resolve repository resources from the actual repo root and plugin resources from the installed plugin root.
- Plugin commands receive `PLUGIN_ROOT` and `PLUGIN_DATA`, plus their `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` compatibility aliases. Their values identify the installed plugin and writable data location. Do not assume user/repo hooks receive plugin variables.
- Input is event JSON on stdin. Preserve event-specific fields and value types in the fixture. Check a script that reads stdin to EOF for a replay that leaves the pipe open.
- Collect script stderr and the first relevant exception frame. Distinguish a spawn failure, interpreter error, input parse failure, missing dependency, and an external-service error.
- For hangs, inspect interactive prompts, waiting child processes, locks, network waits, and recursive invocation before raising the timeout. Check the event's permitted timeout range.

Use bounded, sanitized excerpts from the affected surface's logs and event records. For the CLI, inspect its configured `log_dir`; the default is normally under `CODEX_HOME/log`. Other surfaces can use other log locations. Do not require a log file that is absent, dump whole transcripts, or claim a lack of log output proves that no hook ran.

If a diagnostic command triggers the failing hook, preserve that rejection. Continue with compliant read-only evidence or an isolated fixture. Do not remove the hook as a probe. Avoid starting a nested Codex session with the same hooks during a replay unless recursion is controlled and the action is authorized.

## The command runs, but Codex reports an error or wrong decision

Compare raw stdout and exit status against the specific event contract. Move debug banners, progress text, and logging to stderr when stdout is reserved for structured hook output. A JSON parser accepting the output does not prove that Codex accepts its fields or event name.

| Observation | Interpretation to verify |
| --- | --- |
| Exit `0` with no output | Success with no requested control change. Do not require nonempty JSON solely to replace a valid empty result. |
| Exit `0` with structured output | The process succeeded, but Codex must still validate and interpret the event output. |
| Exit `2` with a reason on stderr | Several decision-capable events use this for a block or continuation. It can be an intentional result. |
| Other nonzero exit, signal, timeout, or malformed output | Inspect execution failure and event-specific handling. Do not assume that the operation was blocked. |
| `decision: "block"` from `PreToolUse` | Can prevent the pending action. Check the reason and policy input. |
| `decision: "block"` from `PostToolUse` | The action has already run. Feedback cannot undo its side effects. |
| `decision: "block"` from `Stop` | Requests another continuation. Check the generated reason, `stop_hook_active`, and the condition required to finish. |
| Plain text from `Stop` or `SubagentStop` | Nonempty plain text is invalid under the current contract; use the supported JSON shape. |
| A context preview instead of the full hook message | Check `additionalContextLimit` and the saved output artifact before calling it lost output. |

Test a suspected loop with successive representative event payloads. Check whether the implementation uses `stop_hook_active`, whether state persists between invocations, and whether the completion condition can become true. Preserve the intended policy; an unconditional success response does not establish a fix.

For asynchronous command hooks, correlate launch and completion records. They do not gate the triggering action. Verify that the event supports asynchronous execution and that a delayed result is being interpreted correctly.

Do not assume that Codex retries failed hooks. The checked official guidance does not define a generic retry policy. Before repeating a trigger, establish whether its action or hook side effects already occurred.

## An MCP hook fails

Inspect `type`, `server`, `tool`, `input`, and the effective timeout. The server must already be connected and expose the named tool; a hook does not start or reconnect it. Check missing template fields and compare expanded argument types with the tool schema. A complete `${field.nested}` placeholder preserves the JSON type; embedding it in text makes a string.

MCP hooks can fail without blocking the original action. `SessionStart` can precede server readiness. Check the tool result and hook output contract separately. Reproduce only with a read-only tool or an authorized fixture when the tool has side effects.
