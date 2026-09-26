# Skill Packages

Read this reference whenever a skill is created, edited, reviewed, compared, or
removed. Apply the common surface-selection and writing rules in `SKILL.md` too.

## Invocation

A model-invoked skill pays permanent context load for its name and description
so the agent can discover it. Use it when the agent must reach the workflow on
its own or another workflow must route to it. A user-invoked skill pays human
cognitive load instead and is appropriate when invocation is deliberately an
operator choice.

For a model-invoked skill, make the description a discriminating context
pointer:

- Front-load the operation or domain users are likely to name.
- State the distinct task branches that should activate the skill.
- Include concrete artifact names when users commonly mention them.
- Add exclusions only when they prevent plausible misrouting.
- Keep detail and procedure out of the description; descriptions may be
  shortened when many skills compete for the initial context budget.

For a user-invoked skill, keep the description as a concise human-facing
summary. Do not spend trigger-list tokens on behavior the model cannot select.

## Package and Progressive Disclosure

Inspect `SKILL.md`, `agents/openai.yaml`, bundled `references/`, `scripts/`, and
`assets/`, plus repo-local callers such as hooks, tests, and `AGENTS.md`
routing.

Keep shared purpose, workflow, essential constraints, and branch routing in
`SKILL.md`. Put substantial mode-specific guidance, schemas, examples, or
procedures in supporting references. Every resource needs an explicit condition
that says when to read, run, or copy it. Do not create a router or resource
directory when the skill has no meaningful branches.

Use scripts for repeated deterministic operations whose reimplementation would
reduce reliability. Use assets only for files copied or adapted into output.
Avoid READMEs, changelogs, installation notes, migration diaries, and duplicated
quick references unless packaging explicitly requires them.

## Surface-Ownership Review

Review the behavior before reviewing its prose:

- Promote a rule to the applicable `AGENTS.md` when correct execution depends
  on it before any task-specific skill can be selected.
- Keep task-specific semantic workflow in the skill even when it applies across
  many repositories.
- Demote branch-only detail to a routed reference when loading it for every use
  obscures the shared workflow.
- Move mechanically enforceable invariants to hooks, validators, scripts, or
  tests; retain prose only for judgment, ownership, or a non-obvious safe path.
- Leave cheap facts in code, configuration, directory structure, or `--help`
  output rather than caching them in instructions.

Treat a misplaced instruction as a functional defect: a perfect rule on the
wrong surface either fails to load when required or taxes every unrelated task.

## Review Workflow

1. Verify structure and reachability:
   - Frontmatter has the required fields and supported local extensions.
   - Folder name, skill name, metadata, and invocation policy agree.
   - Every resource and caller resolves and has a live purpose.
2. Verify factual claims against current primary sources or installed source.
   Confirm referenced APIs, flags, packages, paths, scripts, and commands.
3. Test instruction quality:
   - Triggering information is in the description, not only the body.
   - The body adds durable judgment or workflow beyond model defaults.
   - Freedom is strict where mistakes are costly and flexible where judgment
     matters.
   - Completion criteria are observable and proportionate to the risk.
4. In update mode, correct unambiguous issues within the user's authorized
   scope, then review the resulting package.
5. Validate with the current skill validator and run affected scripts or focused
   tests.

## High-Impact Failures

- **Wrong surface**: the instruction is absent when needed or always loaded when
  conditional.
- **Invisible skill**: the description omits a distinct trigger branch or the
  invocation policy blocks intended discovery.
- **Trigger magnet**: a catchall description attracts tasks the body does not
  own.
- **Tutorial dump**: the body spends context teaching basics rather than
  preserving expert judgment.
- **Orphan resource**: a bundled file has no condition for reaching it.
- **Wrong freedom level**: fragile work is vague or judgment-heavy work is
  rigid.
- **Stale authority**: examples rely on obsolete behavior, paths, or products.
- **Auxiliary clutter**: package files explain history or installation without
  changing agent behavior.

## Severity and Output

- **blocker**: invalid package structure, non-existent required dependency, a
  broken required script, or an instruction that prevents correct use.
- **high**: wrong surface, missing required trigger, contradictory guidance,
  undiscoverable resource, stale major-version behavior, or excess authority.
- **medium**: redundant tutorial content, unclear ownership, poor freedom
  calibration, or outdated minor-version guidance.
- **low**: wording, formatting, or metadata polish without material activation
  or correctness impact.

For audit and update modes, lead with findings in this form:

```markdown
- [severity] [file:line] Problem -- consequence -- required fix
```

Then include validation results, residual risk, and a concise change summary
when files changed. If there are no findings, state that explicitly.
