# Capability selection and change workflow

Read this reference when inventorying candidates, presenting choices, or preparing a harness change. The helper performs deterministic discovery and file transactions; the agent owns interpretation, external evidence, interviews, and behavioral tests.

## Inventory and eligibility

The durable root is `<selected Codex home>/opl/harness/`. `inventory.json` stores the effective discovery snapshot. `decisions.json` stores category choices and their evidence. `runs/<run-id>/manifest.json`, `evidence.jsonl`, and `report.json` store one bounded evaluation. Read those files before resuming. Preserve records across a later discovery; changes in installed state require reconciliation, not a new blank interview.

Keep the complete inventory on disk. Use `cards --home PATH --kind plugin`
to begin with six short entries, then filter by `--source native` or
`--query TEXT` and advance with `--offset N`. Use `--kind skill`, `mcp`, or
`cli` within a selected category. Read full records only for shortlisted IDs;
do not load every cached skill into the root conversation. Registered local
marketplaces are discovered automatically; `--marketplace PATH` adds a local
manifest when the host does not list it. Discovery never upgrades catalogs.

Inventory the effective, user-visible state:

- Global and project instructions that may route a capability; identify the file and ownership of each rule.
- Installed plugin IDs, enabled state, and source marketplace; distinguish a disabled installation from an enabled one.
- Installed skill packages, cached copies, and catalog entries. Page through every available listing; a cached copy or catalog item is a candidate, not an active capability.
- MCP server configuration and actual tool availability; configured or listed does not mean authenticated or working. After shortlisting, retrieve listed tool names and descriptions from available host metadata. Do not start a server merely to complete the inventory.
- Relevant local CLIs and their executable help; a command name alone does not establish supported operations.

Classify evidence as local observation, primary vendor documentation, or unverified claim. For prices and access, check the current provider page and record whether the option has recurring free hosted use, a time-limited trial, a paid tier, or a self-hosted path. Verify eligibility and limits for the user's intended use. For a free operating mode, exclude paid-only and trial-only routes, including any route with a required paid dependency. A recurring free quota or self-hosted path is eligible when its requirements fit. Unknown cost or availability remains unknown in the card. Prefer a local probe or official source over generic descriptions and marketing summaries.

Account for context with the actual host exposure: skill names, paths, and descriptions at initial selection; deferred schema and full skill text when invoked; and tool results and fixed host overhead during use. The inventory's 256-character description summary is per item and leaves its exact name separate. Character counts are an approximation, not proof of token savings. Compare measured or documented exposure before claiming that moving text behind a pointer reduces context.

## Category interview

Present one coherent category at a time. Keep each option card short and identify the exact product or skill name; the 256-character inventory summary limit does not apply to an entire card. State the currently working route first when one exists. Include a useful "keep current" option and a "skip for now" option when those are real choices. Ask only for decisions that change the outcome. Save the selected option, reason, source, and any user constraint with `decide`; then move to the next category. Its JSON input requires `category`, `status` (`selected`, `excluded`, `deferred`, `reviewed`, or `applied`), and `reason`; it preserves additional choice context. On resume, inspect `decisions.json` and ask only about unresolved or materially stale choices.

Eliminate redundant routes before writing new routing text. A broad global rule can silently compete with a skill-specific policy or plugin setting. Scope the change to the supported owner and show before/after behavior. A skill's `agents/openai.yaml` may own implicit invocation; plugin enablement owns whole-plugin availability; a user instruction can express preference only where a supported setting does not. Do not edit an installed cache. Where a capability has no supported configuration control, explain the limitation rather than inventing one.

For instruction routing, keep a compact always-loaded core in the managed section. Put one category's optional detail in its own policy file, then link to a procedural skill or reference only when that category is active. Each pointer must name a real target and a clear condition for reading it. Check that the core, category, and procedure route resolves without pointing back to an earlier layer. Keep a constraint inline until fresh-context tests establish that its conditional route works. Test root routing, documentation-triggered retrieval, and subagent inheritance or retrieval as separate events; success in one does not establish the others.

## Prepared changes

Keep candidate files separate from live targets. The `prepare` input is a JSON list of objects with `target` and `candidate` paths. Check that each candidate is complete, that its target is intended, and that the preview includes the full change. A section headed `Harness Policies (managed by $opl:configure-harness)` has exactly one owner in the global file. On first setup, its absence is normal; review the insertion point and create exactly one section. Duplicate headings or ambiguous ownership are stop conditions. Personal global instructions outside that section belong to `$opl:update-instructions` reconciliation.

For `config.toml`, the transaction accepts ordinary enablement changes and the
narrow OPL startup baseline only. The plugin-root `config.defaults.toml` file
is the versioned source for that baseline. It contains the required feature and
agent defaults. The transaction also reconciles `opl-` role registrations that
point to the discovered OPL role directory. It can add, remove, or rebind those
registrations while it preserves every non-OPL registration and unrelated
configuration. Reject any other configuration change.

Add an ignore marker only after the user chooses to ignore future checks. It
must be `# opl:ignore-config-check version=<plugin version>` near the top of
`config.toml`, after its schema header. A marker for the installed plugin
version short-circuits the startup audit before parsing. OPL removes a stale
marker before it evaluates configuration after an update. The marker does not
disable explicit role reconciliation or `fix`.

Apply only the reviewed plan and retain its receipt. If a concurrent edit invalidates the plan, refresh the candidate and review the affected content. After application, check the effective files and behavior. Use the receipt for a targeted rollback if application fails or the user rejects the result. Do not treat a successful file write as proof that a skill selects correctly in a new session.

Mark a category `applied` only after that verification. After rollback, rediscover
the restored state and update its decision record so a resumed interview cannot
mistake the abandoned proposal for the active configuration. A model, capability,
price, or instruction change invalidates only the evidence that depended on it;
revisit those categories without discarding unrelated decisions.
