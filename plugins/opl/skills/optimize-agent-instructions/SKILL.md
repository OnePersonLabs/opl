---
name: optimize-agent-instructions
description: Optimize the instruction text physically present in global and project AGENTS.md files through clean-context paired behavioral tests. Use when a user wants to consolidate global and project agent guidance, remove steering that duplicates default model behavior, preserve operational instructions, or maintain scope-specific AGENTS.excluded.md records with timestamped source backups.
---

# Optimize Agent Instructions

Optimize only the text physically present in the applicable `AGENTS.md` files. Treat `@` imports and every other referenced file as opaque text. Never open, search, test, or modify their targets.

Create no manifests, audits, reports, staging files, temporary AGENTS files, or session-state files. Keep the candidate inventory, rubrics, test plan, outputs, and decisions in the working context.

## 1. Resolve scope and back up sources

Perform these mechanical steps in the main agent:

1. Resolve the global file as `$CODEX_HOME/AGENTS.md`, falling back to `~/.codex/AGENTS.md` when `CODEX_HOME` is unset. Permit an explicitly supplied global path for an isolated fixture.
2. Resolve the project root with Git when the working directory belongs to a repository. Include `<project-root>/AGENTS.md` only when it exists. Outside Git, include `AGENTS.md` in the explicit project directory when present. Do not discover nested or unrelated AGENTS files.
3. Generate one local-time timestamp in `YYYY-MM-DD_HH-MM-SS` form.
4. Copy each applicable source beside itself as `AGENTS_backup_<timestamp>.md`. Use the same timestamp for global and project files. Refuse to overwrite an existing backup.
5. Read any existing scope-matched `AGENTS.excluded.md` into working context and remember whether it existed so failure recovery can restore it without another backup file.

Backups are immutable recovery sources. Copy them; do not rename the active files.

## 2. Separate candidates from operational material

Classify coherent instruction blocks in memory.

Optimization candidates include agent-behavior steering such as reasoning posture, autonomy, communication, delegation judgment, coding judgment, formatting preferences, and general engineering behavior.

Non-candidates include environment facts, machine paths, browser and documentation routing, API-key placement, tool or skill instructions, shell commands, package-manager commands, project architecture, repository workflows, and `@` import lines. Preserve non-candidates in their current scope and do not test them.

Apply scope by meaning, not origin:

- Move generally applicable behavioral preferences found in the project file into the global candidate set.
- Keep project-specific behavioral constraints and all project mechanics in the project set.
- Avoid duplicating a global rule in the project file.
- Treat headings and source placement as weak evidence. Reorganize by semantic scope and behavior rather than preserving arbitrary provenance-based sections.

Rewrite the active AGENTS files into a baseline state that contains all non-candidates but none of the optimization candidates. Do not create an intermediate file. Newly spawned agents must therefore inherit default model behavior plus operational instructions unrelated to the behavior being tested.

## 3. Plan minimal behavioral test batches

Split the candidate pool into behaviorally distinct instructions, then pack compatible candidates into as few paired tests as possible. Batch candidates when one realistic scenario can create a distinct opportunity to observe each behavior without the instructions interacting, masking one another, or making attribution ambiguous. Keep conflicting, tightly correlated, or scenario-incompatible candidates in separate batches.

Before sampling outputs, define for every candidate in a batch:

- The part of the shared scenario that creates a genuine opportunity to follow or violate the instruction.
- The intended observable behavior.
- An independent scoring criterion that distinguishes a material improvement from stylistic noise.

Do not plan mini-tests for non-candidates. Never execute or simulate custom tools, commands, scripts, integrations, skills, OpenSpec workflows, RTK behavior, or unknown side effects.

## 4. Run clean-context paired tests

For each batch, use new subagents that do not inherit the main conversation:

1. Spawn a baseline agent with `fork_turns="none"`. Give it only the shared scenario. Forbid tools, file reads, file writes, and discussion of the test setup. Require output only.
2. Spawn a steered agent with `fork_turns="none"`. Give it the identical scenario plus only the candidates in that batch. Apply the same output-only restrictions.
3. Spawn a fresh evaluator with `fork_turns="none"`. Provide the predefined per-candidate rubrics and anonymized outputs in randomized order. Do not reveal which output was steered. Require a separate judgment for each candidate about material behavioral differences and intended effect.

Do not reuse test or evaluator agents across batches or follow-up pairs. Sequence agents as needed to respect concurrency limits.

Use these decision rules:

- Retain a candidate when its independently scored signal shows a material change in the intended direction.
- When a candidate's signal is ambiguous, isolate only that candidate in a sharper follow-up pair.
- When the first pair shows no material difference for a candidate, run a second sharper scenario before declaring that instruction redundant; combine multiple no-signal candidates again only when attribution will remain clean.
- When steering changes behavior in the wrong direction, rewrite the instruction and retest it from fresh contexts.
- Retest any rewrite that changes semantics. Purely editorial compression may reuse the existing result.
- Never activate an instruction that fails to produce its intended effect reliably. Exclude it with the applicable reason.

## 5. Rebuild the active files

Reconstruct both active files directly from the backups, the preserved non-candidates, and the test decisions.

For the global file:

- Consolidate overlapping general steering into a coherent section hierarchy.
- Organize by behavior rather than original file, source section, or provenance.
- Use imperative language, one behavior per bullet, clear scope, minimal headings, and shallow Markdown structure.
- Remove duplicated rationale, vague intensifiers, motivational prose, and unnecessary examples.
- Keep global environment and operational material outside CORE under descriptive sections.

For the project file:

- Keep project architecture, commands, dependencies, tools, workflows, and project-specific behavior.
- Remove guidance promoted to the global file.
- Preserve useful non-candidates without testing or optimizing them.

Preserve semantic force unless a tested rewrite intentionally changes it. Do not silently omit material that was not an optimization candidate.

## 6. Record excluded steering

Use a scope-matched exclusion file only when that scope has excluded candidates:

- Global: beside the global file as `AGENTS.excluded.md`.
- Project: beside the project file as `AGENTS.excluded.md`.

Append exactly one invocation block per affected scope:

```markdown
# <YYYY-MM-DD_HH-MM-SS> excluded by optimization-agent-instructions

## <candidate label>

<original instruction text>

Reason: <one concise sentence describing redundant default behavior or failed steering>
```

Place every exclusion for the invocation beneath that single level-one heading. Preserve the original instruction text. Do not overwrite older blocks. Do not create or modify an exclusion file when the scope has no exclusions.

## 7. Recover on failure and report completion

If the workflow is interrupted, cancelled, or cannot finish in the current turn:

1. Copy every timestamped backup over its active AGENTS file.
2. Restore each pre-existing exclusion file from the content retained in working context, or delete a newly created exclusion file.
3. Leave the timestamped AGENTS backups in place.

On success, verify:

- The global and applicable project AGENTS files are non-empty.
- The files contain no duplicated or provenance-only section splits that the semantic reorganization should have consolidated.
- Non-candidates remain in their proper scope.
- Retained steering matches successful tests.
- Exclusion blocks use the invocation timestamp and correct scope.
- No manifest, audit, report, temporary AGENTS, or session-state file was created.

Report only the active files, backup files, exclusion files actually changed, the number of candidates retained or excluded, and any validation limitation. Do not create a separate report artifact.
