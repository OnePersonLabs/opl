# Bounded behavioral tests

Use this procedure for the comparisons planned in `SKILL.md`. It tests AGENTS
behavior and routing with disposable fixtures. Do not add permanent invocation
tests or run production workers to obtain an activation receipt.

## Isolate each comparison arm

Create a temporary directory outside the target repository. Give each arm its
own project directory, `.codex/config.toml`, `.codex/agents/`, and Codex home.
Initialize each test project with `git init --quiet` before inspecting or running
Codex so repository checks and project discovery use the fixture root.
Load only that arm's instruction variant. For a skill proposal, copy the baseline
or proposed skill package into the arm's fixture and keep untouched content
identical. Keep the scenario, capability descriptions, fixture data, tools, and
compute settings equal, except the instruction or discovery metadata being tested.
Do not resume sessions or pass the optimizing conversation to executors.

Use the same supplied task plan for both arms. It must ask for realistic work
products, not compliance judgments. Keep scoring criteria and expected
activations with the root. A missing instruction belongs in the tested variant,
not in a prompt that tells the executor how to compensate for it.

Use supported authentication without printing secrets or changing real account
configuration. Trust only the temporary project through its isolated home so
Codex loads its project configuration. Disable unrelated hooks, plugins,
integrations, and instruction sources in the fixture. For routing comparisons,
keep the relevant enabled skill names, descriptions, and invocation policy;
replace their task work with fixture acknowledgements. Record omitted context
that could change the conclusion.

## Replace every selectable worker

Copy each available role's actual `name` and `description` into a replacement
TOML under the test project's `.codex/agents/`. Register every name through
`agents.<name>.config_file` in `.codex/config.toml`. Paths are relative to that
config file, so use `agents/<name>.toml`. Match the registration name and TOML
`name`. Include generic/default routes that the executor can select. If a route
cannot be replaced or constrained to a mock return, do not run delegation cases.

Keep name and description exact so the experiment tests production selection.
Replace the original `developer_instructions` completely, including inherited
work procedures. Set model and effort in each replacement. This complete
example uses OPL's explorer description; repeat the shape with each actual role:

```toml
name = "opl-explorer"
description = "Investigate a bounded repository question without editing, tracing the relevant control or data flow."
model = "gpt-6-luna"
model_reasoning_effort = "low"
sandbox_mode = "read-only"
developer_instructions = """
You are an activation test double. Return exactly the following JSON and stop:
{"activation":"opl-explorer","mock_result":"Fixture owner is sample.py; no investigation was performed."}
Do not use tools, inspect files, edit anything, perform the assigned work,
ask questions, delegate, or launch another process.
"""
```

Corresponding test project `.codex/config.toml`:

```toml
model = "gpt-6-luna"
model_reasoning_effort = "low"
sandbox_mode = "read-only"

[agents]
enabled = true
default_subagent_model = "gpt-6-luna"
default_subagent_reasoning_effort = "low"
max_concurrent_threads_per_session = 3

[agents.opl-explorer]
description = "Investigate a bounded repository question without editing, tracing the relevant control or data flow."
config_file = "agents/opl-explorer.toml"
```

This example alone is not full coverage when other roles are available. Build
replacements from the live inventory, not a fixed list. Apply the same mock-only
boundary to unnamed/default children. Do not expose unmocked production roles.

Parse all TOML and resolve every registration before a model call. Use installed
Codex help, prompt-input inspection, and app-server `config/read` to verify
instruction context, effective registrations, trust, and overrides. Prompt-input
output alone does not inventory role tool descriptions. Verify replacement instructions from recorded child
context and their fixed returns. If discovery fails or a real worker instruction
remains effective, stop and repair the fixture; never substitute a live probe.

## Execute one compact plan per arm

Pass a UTF-8 prompt through stdin. Invoke `codex exec` with explicit `--model`
and `-c model_reasoning_effort=low`, the arm's project as `--cd`, and `--json`.
Use the least costly supported model; `gpt-6-luna` is the local starting point.
Set `CODEX_HOME` only for that child process. Save outputs outside the target
repository. Keep the existing command timeout contract and use the host's
completion mechanism; do not introduce a polling loop or detached deadline.

Pure output cases need no tools. Delegation cases permit bounded orchestration
and mock returns. Routing cases may read only fixture skill instructions. The
shared fixture boundary must prevent real project work without instructing the
root to select a role or skill. Terminate a run that attempts unmocked work and
record the failed boundary, rather than scoring its output as safe evidence.

When `request_user_input` is the behavior under test, use an interactive CLI
with the same fixture and compute settings. Observe the real tool call and
provide the predefined reply. Unsupported exec calls, narrated questions, and
mocked tool names do not establish interactive question behavior.

Read recorded spawn calls, child context, and mock completions. CLI JSON output
can omit native spawn details; inspect the saved rollout when needed. An
activation passes only when the expected role was actually selected and its
mock returned without work or descendants. Record extra or missing activations.

Use paired results to decide instruction wording, and keep the mocks' limit
explicit: they exercise role selection and coordination, not the original role
instructions. Report actual model/effort, elapsed time and usage when available.
Remove temporary credentials and fixtures after collecting necessary evidence.

Verify format and precedence against the installed Codex version. Official
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
documents `config_file` resolution and project trust;
[subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents)
documents standalone role fields and configuration overrides.
