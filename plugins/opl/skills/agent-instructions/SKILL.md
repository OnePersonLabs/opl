---
name: agent-instructions
description: Author, update, or review AGENTS.md and SKILL.md; audit, score, or restructure hooks and other agent instructions.
---

# Agent Instructions

Treat an instruction system as a production control surface. Make future agents
take a predictable process without forcing identical output.

## Choose the Mode

- **Author or update** when the user asks to create, change, consolidate, or fix
  instructions. Preserve unrelated user changes and review the resulting system.
- **Audit** by default when the user asks to review. Inspect and report without
  editing.
- **Score** when the user asks for a score, grade, comparison, or quantitative
  readiness assessment. For a combined update and score request, update first
  and score the final state.

## Establish the Instruction System

Before editing, identify the requested behavior, its intended scope, and the
nearest current owner. Read the target, applicable `AGENTS.md` files, pointers,
callers, hooks, validators, tests, metadata, and relevant dirty diff. Search for
duplicate or contradictory guidance before adding another rule.

For current Codex product or format claims, use official OpenAI documentation.
Prefer installed source and executable help for local tool behavior.

## Select the Surface

Place each meaning at the narrowest surface that still loads whenever it is
needed:

| Behavior                                                             | Owning surface                                                                             |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Baseline stance or constraint needed on every in-scope task          | The nearest applicable `AGENTS.md` or `CLAUDE.md`                                          |
| Reusable task-specific judgment or semantic workflow                 | A model-invoked skill when automatic discovery is valuable; otherwise a user-invoked skill |
| Conditional detail needed by only one branch                         | A routed reference loaded from its owning instruction file                                 |
| Mechanically checkable invariant or repeated deterministic operation | A hook, validator, test, or script, with prose only for non-obvious intent                 |
| Skill discovery policy or UI metadata                                | Skill frontmatter and `agents/openai.yaml`                                                 |
| Fact cheaply discoverable from code, config, or command output       | The environment as source of truth; add prose only for the hidden reason or gotcha         |

Apply scope by meaning. Global preferences belong in global guidance;
repository conventions belong at the repository root; module-specific rules
belong near the module. Do not trap always-needed behavior behind skill
selection, and do not keep a task-specific workflow always loaded.

When any skill package is in scope, read
[references/skill-packages.md](references/skill-packages.md). When scoring a
skill, also read
[references/scoring-rubric.md](references/scoring-rubric.md).

## Context Pointers

A **context pointer** is always-loaded wording that names out-of-context
material and states when to reach it. A skill description and an `AGENTS.md`
line that routes to a reference are both pointers. Their wording determines
whether the material is reached reliably.

- Front-load the leading use case or trigger word.
- Encode one trigger per genuine workflow branch; collapse synonyms for the
  same branch.
- Name the scope and useful boundaries without turning the pointer into an
  exhaustive capability list.
- Keep mandatory behavior inline when a sharpened pointer still cannot make
  routing reliable.

## Information Hierarchy

Every instruction spends **context load** when it is always present and
**human cognitive load** when a person must remember how to reach it. Spend
always-loaded context on invariant behavior and short, discriminating pointers.
Spend human choice where human judgment is meaningful.

Arrange content by when it is needed:

1. Put the shared ordered actions in the entrypoint.
2. Keep short reference material beside the step or decision it supports.
3. Disclose substantial branch-specific rules, schemas, examples, or procedures
   behind a pointer and load only the selected branch.

Split by invocation only when a branch needs an independent trigger. Split by
sequence only when visible later steps cause premature completion of a fuzzy
earlier step. Otherwise, prefer co-location: keep a concept's definition,
rules, and caveats together.

End each operational step with a checkable completion criterion. Make it
exhaustive when missing one item would matter. Sharpen a vague bound before
adding more process.

## Write for Behavioral Force

Use **leading words**: compact concepts already present in the model's
pretraining that anchor the intended behavior. Repeat the token where it
reinforces execution or invocation, not the surrounding explanation.

Write the positive target behavior. Use a prohibition only for a real
guardrail that cannot be expressed positively, and pair it with the safe path.
Match specificity to risk: constrain fragile, permission-sensitive operations;
state outcomes and decision criteria where multiple approaches are reasonable.

Keep one source of truth for each meaning. Replace a bad instruction rather
than adding a counterweight. Delete tutorials, motivational prose, history,
restated environment facts, and sentences that do not change model behavior.
Treat size as an attention cost, not a quality signal.

## Complete the Work

For updates, review every touched instruction file and its dependencies after
editing. Fix unresolved references, placeholders, and duplicate or conflicting
rules, including defects that predate the edit.

For an audit or update, report findings ordered by consequence with file
evidence, then validation, residual risk, and a concise change summary when
files changed. For authoring work, explain any consequential surface-placement
decision.

Validate syntax and metadata with the repository's current validators, run
focused tests for affected hooks or scripts, and use behavioral evaluation only
when wording itself is the uncertain mechanism. Do not add static wording tests
that merely freeze prose.
