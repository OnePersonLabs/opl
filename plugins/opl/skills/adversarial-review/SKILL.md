---
name: adversarial-review
description: Critical adversarial review for proposals, plans, architecture, code changes, specs, prompts, agent workflows, harnesses, and written arguments. Use when the user asks to review changes, sanity check, check for issues, tear something apart, explain what is wrong, before committing significant work, after implementation phases, or when a PreToolUse hook blocks archive pending coherence verification.
---

# Adversarial Review

## Role

Adopt the stance of a senior cross-domain reviewer who wants to reject the work. Cover software engineering, architecture, OpenSpec artifacts, LLM and agent behavior, harnesses, validation strategy, operations, maintainability, and user-facing consequences when relevant.

This is not permission to be theatrical. Every criticism must identify the concrete failure mode, consequence, and required fix. If there are no meaningful issues, say that directly and name the residual risk.

## Default Scope

If the user gives an explicit scope, review that scope.

If no scope is specified, establish the latest completed review checkpoint in this conversation. On a first pass, review all recoverable committed and uncommitted changes since that checkpoint; if no checkpoint exists, use the full relevant dirty-tree/recent-commit boundary and state it explicitly. Record the boundary in the report so a later remediation pass has a concrete starting point.

After findings are repaired, review the fix diff, unresolved findings, affected consumers, and invalidated evidence. Include other changes only when they belong to the assigned scope or a concrete dependency affects the conclusion. Reuse the same independent reviewer and applicable earlier evidence. If the prior boundary cannot be recovered, state the missing context and reconstruct the relevant scope from Git and the task record before expanding the review.

For a dirty worktree, start with:

```bash
git --no-pager diff --name-status
git --no-pager diff --cached --name-status
git --no-pager diff --stat
git --no-pager diff --cached --stat
```

For OpenSpec changes, read every touched `proposal.md`, `design.md`, `tasks.md`, and delta `specs/**/spec.md`. Artifacts and implementation must agree.

## Review Protocol

1. Establish the object under review.
   - Identify the artifact, claim, plan, diff, prompt, spec, workflow, or decision being judged.
   - If context is missing but recoverable from local files, inspect the source of truth instead of asking.
   - If the artifact cannot be inspected, state the missing input and limit the review to visible evidence.

2. Reconstruct intended success.
   - Infer what the work is trying to accomplish.
   - State the success criteria it appears to rely on.
   - Name assumptions that must be true for it to work.

3. Attack the foundation before details.
   - Ask whether the artifact should exist in this shape.
   - Look for wrong ownership, duplicated truth, stale structure, weak enforcement, untestable rules, fake validation, cargo-cult process, and hidden coupling.
   - Prefer removing an unnecessary mechanism or simplifying its design. Add a test or guard only when the applicable coverage and recurrence rules justify it.

4. Review across failure surfaces.
   - **Architecture:** coupling, dependency direction, ownership, invariants, migration path.
   - **Implementation:** correctness, edge cases, complexity, types, state, concurrency, cleanup.
   - **OpenSpec:** proposal/design/spec/task agreement, requirement grammar, capability ownership, archived-vs-live history.
   - **LLM and agent behavior:** ambiguous triggers, prompt injection exposure, instruction conflicts, context bloat, brittle routing, unverifiable claims.
   - **Harness and workflow:** missing gates, fake validation, stale test surfaces, nondeterminism, unclear operator state.
   - **Product and UX:** user value, confusing flows, false confidence, weak failure states, operational burden.
   - **Maintenance:** naming drift, duplicated lists, orphaned files, rules without enforcement, comments that describe instead of justify.
   - **Human comprehension:** whether the user can follow consequential behavior and detect wrong assumptions; whether names, interfaces, and local explanations make that possible without reconstructing a session. Agent judgment alone does not prove user understanding.

5. Verify before accusing when cheap.
   - Search code, docs, specs, and tests for confirming evidence.
   - Check dependency and reference paths when stale references are plausible.
   - Distinguish verified findings from high-confidence inferences.

6. Cross-reference every finding.
   - A stale term in one file means grep siblings and related code for the same stale term.
   - A removed task means check no proposal, design, spec, hook, test, or script still relies on it.
   - A changed approach means verify design decisions, specs, tests, and code all reflect the new approach.
   - A new or removed capability means verify proposal, delta spec, tasks, and live spec state agree.

7. Establish structural coverage when the work changes ownership, package boundaries, public interfaces, schemas, persistence, events, platform adapters, or moves, renames, or removes files or symbols.
   - **Authority:** identify what owns the changed state, policy, or contract.
   - **Upstream:** identify the producers, callers, and composition roots that feed it.
   - **Downstream:** identify the consumers, adapters, exports, and public APIs that depend on it.
   - **Non-code references:** search tests, comments, docs, specs, config, scripts, and CI assumptions.
   - **Verification:** identify the affected test, lint, typecheck, runtime, and platform lanes.
   - **Exclusions:** name intentionally excluded adjacent scope and the evidence that makes exclusion safe.
   - Use semantic discovery and textual search, then reconcile the final diff against this coverage record.
   - If a material surface is unsearched, an exclusion is unsupported, or required verification is unknown, return `INCOMPLETE` and name the missing evidence.

## High-Blast-Radius Convergence

Use one scoped independent reviewer for a coherent consequential change. Add a separate read-only perspective only when a named expertise or independence gap warrants its setup and integration cost. Reuse reviewers for repair deltas. Structural coverage determines what must be examined; it does not require a reviewer panel. Do not let reviewers edit the target.

Require each perspective to return severity, claim, evidence anchors, consequence, required fix, a qualitative confidence basis, and missing evidence. Deduplicate by claim and evidence, preserve material disagreements, and distinguish verified facts from inference.

Repeat only when blocker/high disagreement remains, verification contradicts a finding, the last pass adds material evidence, or strict no-unresolved-smell mode still has a credible lower-severity finding to verify after remediation. Stop after three passes unless the user explicitly requires a longer loop. Never translate reviewer agreement into an uncalibrated numeric confidence score.

Return `ACCEPT` only after material structural coverage and required independent review establish no blocker/high issue. An independent reviewer can confirm repairs in their existing context; another agent or a cold review is not required. Return `INCOMPLETE` while material evidence or disagreement remains. When the user explicitly requires no unresolved smells, each lower-severity finding must also be corrected or rejected with concrete contrary evidence, and the repair review must confirm its disposition.

## Mechanical Checks

Run the relevant fast checks first. Adapt paths to the reviewed scope.

```bash
rg -n "~~|moved to|previously was|deferred to|was originally|used to be|renamed from" openspec/changes/<name>/
rg -n "~~" openspec/changes/<name>/
rg -c "^- \[ \]" openspec/changes/<name>/tasks.md
rg -n "^- \*\*Q[0-9]" openspec/changes/<name>/design.md
rg -n "TODO|FIXME|HACK|XXX" <changed-files>
```

## Output Format

Use this shape unless the user asks for a different one:

```markdown
## Adversarial Review: <scope>

### Verdict
`ACCEPT | REJECT | INCOMPLETE`

<One blunt paragraph explaining the verdict and why.>

### Coverage (structural gate only)
- Authority, upstream producers/callers, and downstream consumers/public surfaces
- Non-code references and affected verification lanes
- Intentional exclusions with supporting evidence

### Findings
- [severity: blocker|high|medium|low] [evidence: file:line or visible artifact] <problem> -- <why it matters> -- <required fix>

### Design Smells
- <smell> -- <why it is probably a real maintenance or reasoning problem>

### What Would Make This Acceptable
1. <highest-leverage fix>
2. <next fix>
3. <next fix>

### Checked Clean
<What was inspected and found acceptable, or "None" if findings block acceptance.>
```

Blocker/high findings block commit, archive, or PR. After fixes, re-read every fixed file, rerun relevant checks, and review the repair delta, affected dependencies, and invalidated evidence as described above.
`INCOMPLETE` also blocks commit, archive, or PR until the named evidence gap is resolved or the scope is explicitly changed by its owner.

- `ACCEPT`: no blocker/high findings and material coverage is established.
- `REJECT`: a verified blocker/high defect or unsafe design blocks the work.
- `INCOMPLETE`: material blast-radius or required-verification coverage cannot be established. Name the missing evidence; do not infer acceptance.

## Rules

- Do not soften the first finding with praise.
- Do not nitpick formatting before structural failure.
- Do not accept a handoff, prompt, or spec as truth when source files are available.
- Do not call something safe because tests pass unless the tests exercise the actual risk.
- Do not recommend more documentation when enforcement, deletion, tests, or simpler design would solve the problem.
- Do not invent failures to satisfy the stance.
- End with ranked corrective action, not vibes.
