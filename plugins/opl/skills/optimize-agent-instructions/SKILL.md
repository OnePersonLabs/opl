---
name: optimize-agent-instructions
description: Minimize AGENTS.md guidance or proposed AGENTS and skill instruction changes through phrase-level scrutiny and bounded behavioral comparisons.
---

# Optimize Agent Instructions

Treat every in-scope instruction span as unproven, down to individual
clauses, qualifiers, and phrases. Assume each part is verbose, unnecessary,
harmful, misplaced, and underspecified. Check whether its abstraction makes
triggers, actions, or fallbacks unreliable. Seek evidence against each hypothesis.
Existing wording, familiarity, and passing a whole-rule test do not justify every
phrase.

Pursue concise instructions that cause useful behavior, load at the right scope,
and state observable conditions and actions. Preserve required outcomes and
permission boundaries; scrutiny alone does not authorize their removal.

Read [$simplified-technical-english](../simplified-technical-english/SKILL.md)
and use it for instruction prose. Preserve quotations, code, identifiers, and
commands exactly. Text intended for non-instruction use keeps its appropriate
writing mode; do not impose instruction style on it.

## Choose scope

- **Full AGENTS optimization:** For a standalone request, optimize text physically
  present in the selected global and project AGENTS files. Use all steps below.
- **Proposed changes:** When `$agent-instructions` authors or changes AGENTS or
  any skill instruction text, optimize only its proposed additions and edits.
  A new file's instruction text is all proposed text. Use steps 2--5 on that
  delta and return the revised proposal to the authoring workflow. Do not run
  whole-file discovery, create AGENTS backups or exclusions, or replace active
  files through this mode.

In Proposed changes mode, read the baseline, diff, and whole affected instruction
system. If an unchanged part must change with the proposal to preserve coherence,
include that necessary companion edit before optimization. Keep unrelated text
and user edits intact; do not optimize the whole file by default.
Account for each proposed phrase and preserve required outcomes.
Compare the baseline with the proposal in fixtures only when behavior needs
testing. Return the revised diff, decisions, and verification limits; the
authoring workflow owns application and final checks. Do not claim required
optimization completed if a conflicting or untested required outcome remains.

Treat imports and arbitrary referenced content as opaque. Review pointer wording
without expanding the editing scope. Enabled capability metadata inspected
below is routing evidence, not another editing target.

Keep the inventory, rubrics, plan, and decisions in working context. Create no
permanent manifests, audit reports, staging files, or session-state files.
Temporary test fixtures and execution evidence are permitted outside the target
repository; they must not alter the user's active instruction or role files.

## 1. Resolve scope and preserve recovery

Perform these steps in the main agent:

1. Resolve the active Codex home from `CODEX_HOME`, otherwise `~/.codex`. Select
   its effective global file, including `AGENTS.override.md` precedence. Permit
   an explicit global path for an isolated fixture.
2. Resolve the project root with Git, or use the explicit project directory
   outside Git. Select its effective root AGENTS file when present. Do not
   discover nested or unrelated AGENTS files.
3. Generate one local timestamp in `YYYY-MM-DD_HH-MM-SS` form. Copy each selected
   source beside itself as `AGENTS_backup_<timestamp>.md`. Refuse to overwrite
   an existing backup. Keep the source paths and initial bytes for comparison.
4. Retain the exact bytes of each existing scope-matched `AGENTS.excluded.md`
   in working context, or record that it did not exist.

Keep backups immutable. Leave active files intact until test decisions and
validation are complete. Run instruction variants in isolated fixtures.

## 2. Scrutinize every part

Account for every section, instruction, sentence, clause, and meaningful phrase.
No category is exempt: include operational instructions, commands, environment
facts, formatting, delegation, and context pointers. Preserve identifiers,
command syntax, and factual values exactly when their content remains needed.

For each part, establish its required outcome and the smallest wording that can
cause it. Ask what changes if the part is removed and what it displaces or delays.
Choose its owner: AGENTS, a skill, configuration, or executable enforcement.
Do not move content to an unauthorized surface; report that limit.

Inspect the currently enabled skill names, descriptions, and invocation policy,
plus the available role names and descriptions. A cached package is not proof
of enablement. Read additional skill routing instructions only when needed to
establish a specific conflict; do not execute that workflow. Identify concrete
overlap, competing triggers, and missing conditions. Do not invent a conflict
merely because wording is abstract.

Assume implied delegation will not happen. A role name, description, or sentence
about delegation does not establish activation. Identify the task condition,
expected role, work boundary, and action when delegation is unavailable or
inappropriate. Test actual selection when that uncertainty affects a decision.

Choose deletion, compression, a concrete rewrite, consolidation, or relocation
within scope. Replace harmful wording instead of adding a counterweight. Convert
vague judgment into a condition, action, and fallback when reliable execution
requires them. Do not replace useful judgment with an exhaustive checklist.

## 3. Plan the fewest useful shots

Before any AI run, define the decision each comparison will resolve. For each
tested part, specify a realistic opportunity, expected observable behavior,
contrary evidence, and an independent pass criterion. Use deterministic checks
for syntax and facts. Behavioral tests must resolve wording uncertainty, not
restate instructions or preserve exact prose in permanent tests.

Pack compatible opportunities into one scenario plan per shot group; use one
group when possible. Give each behavior a distinct observable result. Separate
mutually exclusive cases or cases that cue, mask, or change another result.
Plan normal and boundary opportunities together when they remain independent.
Keep rubrics, expected role names, and the comparison purpose out of executor
prompts. Do not tell an executor to activate the behavior being measured.

Compare identical scenarios in fresh contexts. Test usefulness with and without
the candidate. Test compression against the original wording. For phrase-level
questions, remove or replace that phrase while holding the rest constant. A
whole-rule improvement does not establish that each surviving clause is needed.
When behavioral tests are needed, compare the original and final proposed
instruction system to detect interactions that isolated comparisons missed.
Reuse a valid paired result when it already covers that final state.

Start every executor, mock worker, and AI evaluator with the least costly
available model and its lowest supported effort. Set both explicitly; do not
inherit production role settings. `gpt-6-luna` at `low` is the local starting
point when available. Escalate only when a recorded limitation of the cheaper
run prevents the decision, and keep comparison arms at equivalent settings.
Record unavailable cost or runtime measurements as unknown.

Read [references/behavioral-tests.md](references/behavioral-tests.md) before
preparing fixtures or executing tests. Apply the host's AI permission rules;
optimization is not standing permission for model tests. Batch authorized AI
checks at the end of the root turn, after independent work is complete.

## 4. Run bounded comparisons

Use isolated `codex exec` runs for normal cases. Use an interactive Codex CLI
when the tested behavior requires an interactive tool such as
`request_user_input`; an exec error does not test successful question handling.
Give each run a compact plan that exercises all compatible opportunities
indirectly. Use fixture-only tools when actions are necessary, and output-only
restrictions for cases that do not need tools. Do not run real integrations,
custom commands, skill workflows, or project work as test side effects.

For delegation cases, replace role instructions in the test directory's
`.codex/agents/` and register those files in its `.codex/config.toml`. Preserve
real role names and descriptions. Each replacement must acknowledge activation,
return a fixed mock result, and stop without tools, edits, or descendants. Do
not instrument or temporarily edit the user's production profiles.

Verify fixture discovery and effective overrides before sampling. Collect
actual tool events and mock returns. Missing expected activation is a failed
selection. An executor's claim that it delegated is not evidence. Mock receipts
establish routing only; they do not establish production worker competence.

Score each part against its predefined criterion. Use mechanical evidence when
it decides the result. When judgment needs an AI evaluator, use one fresh
context for compatible results with anonymized, randomized comparison arms.
Provide the rubrics and evidence, but no implementer verdict or arm labels.

## 5. Decide and rebuild

- Keep wording only when its useful effect, necessary fact, or required outcome
  justifies its attention cost. Use the shortest successful form.
- If a comparison shows no useful difference, use a sharper independent
  opportunity before declaring the part redundant. Batch unresolved parts when
  attribution stays clear; reuse already-planned boundary cases when suitable.
- If wording degrades behavior, rewrite or exclude it. Retest semantic rewrites.
- If a result is ambiguous, isolate only that uncertainty. Do not keep broad
  wording because one clause helped, or delete necessary behavior because a
  spot test could not observe it.
- If required behavior still fails, fix its trigger or ownership within scope.
  Report a blocked surface change or untested requirement instead of claiming
  optimization succeeded.

For Full AGENTS optimization, rebuild from backups and decisions. Organize by
behavior and scope, not provenance. Put general preferences globally and
project-specific behavior in the project file. For Proposed changes, revise
only the supplied delta within its authorized surfaces. Remove duplication and
padding. Keep needed mechanics where they apply; review each phrase as above.
Preserve conditions, exceptions, quantities, and requirement levels unless an
authorized, tested decision changes them.

Verify complete in-scope accounting, required outcomes, routing, and any required
combined comparison. In Proposed changes mode, check that the revised proposal
includes necessary companion edits and leaves unrelated text unchanged, then
return it. In Full AGENTS optimization,
check that each active file still matches its initial bytes before replacement.
If another writer changed it, reconcile that change before replacement.

## 6. Record exclusions and complete

When a scope has excluded text, append one block to its `AGENTS.excluded.md`:

```markdown
# <YYYY-MM-DD_HH-MM-SS> excluded by $optimize-agent-instructions

## <instruction or phrase label>

<exact original excluded text>

Reason: <concise evidence-based reason>
```

Use the invocation timestamp. Keep all exclusions beneath that one heading for
the scope. Preserve earlier blocks and record exact excluded fragments rather
than marking an entire retained instruction excluded. Do not create or modify
an exclusion file when that scope has no exclusions.

Verify non-empty active files, source accounting, correct scope, no unnecessary
duplication, successful retained steering, and correct exclusion records.
Remove temporary fixtures after collecting results; retain execution evidence
only when needed to explain a result. Create no separate report artifact.

On interruption or failure, restore only this invocation's writes from the
immutable AGENTS backups and retained exclusion bytes. Delete newly created
exclusion files. If a concurrent edit prevents safe restoration, preserve it
and report the recovery source. Leave the timestamped AGENTS backups in place.

Report changed active, backup, and exclusion paths; counts retained and excluded;
test groups and actual model/effort; expected and observed activations; and
validation limits. A spot test supports only its exercised opportunities.
