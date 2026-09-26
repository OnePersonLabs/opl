---
name: review-changes
description: Cold Repository Audit After Large-Scale Changes. Use in a new session when reviewing a large series of completed changes made by another agent.
---

# Cold Repository Audit After Large-Scale Changes

You are reviewing a large series of completed changes made by another agent.

This is an independent forensic engineering audit. You did not participate in the implementation and must not inherit, reconstruct, defend, or continue the implementing agent’s reasoning.

## Critical constraint

Do not modify any files during this phase.

Do not begin fixing findings as you discover them. First build a complete model of what changed, identify systemic causes, and produce a consolidated audit.

The current branch is an untrusted artifact, not an authoritative design.

## Inputs

Determine:

- the appropriate baseline commit before the large change;
- the current HEAD;
- the original requirements, plans, specifications, issues, or stated intent;
- the complete changed-file surface between baseline and HEAD;
- any relevant repository conventions that clearly predate these changes.

Use the baseline version of the repository to distinguish preexisting architecture from patterns introduced by this change.

Do not assume that current tests, comments, types, abstractions, or repeated patterns prove that the implementation is correct.

## Audit objective

Review the work as a skeptical senior engineer encountering the proposed change for the first time.

Determine not merely whether the code can work, but whether the change has the shape that a mature, idiomatic, maintainable implementation should have.

Look for places where the implementation:

- solved the wrong problem;
- misunderstood an existing abstraction or framework primitive;
- created machinery that a conventional implementation would not need;
- converted a temporary obstacle into permanent architecture;
- duplicated responsibility across layers;
- added adapters, wrappers, synchronization, state, flags, configuration, or indirection to compensate for an earlier mistake;
- preserved a false constraint instead of eliminating it;
- made later changes necessary only because of an earlier change in the same series;
- caused tests, types, interfaces, or documentation to conform to the implementation rather than verify the intended behavior;
- produced locally consistent code that is globally unnecessary or incoherent.

## Reconstruct the expected shape first

Before judging individual lines, independently answer:

1. What problem was this change supposed to solve?
2. What are the essential domain concepts and invariants?
3. Which layer should own each responsibility?
4. What would the simplest conventional architecture for this requirement look like?
5. Which framework, platform, language, or library primitives would normally be used?
6. What would likely exist in a mature reference implementation?
7. What would probably not exist in a mature reference implementation?

Create this expected model without using the current implementation as the starting point.

Then compare the implementation against it.

## External calibration

When the correct architectural or framework approach is uncertain, research it.

Prefer, in order:

1. current official documentation;
2. official examples and maintained reference applications;
3. respected, actively maintained production repositories;
4. current ecosystem consensus and established conventions.

Search for how mature implementations solve the underlying requirement.

Do not search primarily for how to repair, justify, or refine the exact workaround found in this repository.

Absence matters. If a substantial local mechanism does not appear in mature implementations of the same problem, investigate why.

## Independent audit lenses

Use independent subagents or isolated analysis passes where available. Give each reviewer the requirements, baseline, current diff, and relevant source files, but not the implementing conversation or another reviewer’s conclusions.

At minimum, perform these lenses:

### Architecture and ownership

Inspect boundaries, dependency direction, domain placement, layering, module responsibilities, public interfaces, state ownership, lifecycle ownership, and cross-platform concerns.

### Framework and ecosystem idiom

Identify custom mechanisms that duplicate or fight framework primitives, package conventions, platform facilities, build tooling, configuration systems, or standard project structure.

### Causal complexity

Trace why each new abstraction, wrapper, flag, cache, queue, synchronization mechanism, compatibility layer, and exceptional path exists.

For each one, ask whether it solves an intrinsic requirement or a problem introduced by another part of this change.

### Behavioral correctness

Trace important flows end to end. Inspect state transitions, failure behavior, retries, cancellation, concurrency, persistence, initialization, cleanup, error propagation, and boundary conditions.

### Contract integrity

Determine whether tests, types, schemas, interfaces, comments, mocks, and documentation enforce the original intent or merely describe the new implementation.

Look for tests that prove the mechanism works while failing to prove the user-visible or architectural requirement.

### Simplicity and deletion

Identify code that could disappear if the correct abstraction, ownership boundary, data model, or framework facility were used.

Prefer removal of false premises over refinement of their consequences.

### Change propagation

Find clusters where one questionable decision caused modifications across many files.

Distinguish legitimate cross-cutting changes from contamination radius.

## Root-cause compression

Do not report fifty isolated symptoms when they arise from three mistaken premises.

Cluster findings by shared cause.

For every cluster, identify:

- the originating decision or assumption;
- the downstream code it forced into existence;
- why the pattern appears locally reasonable;
- why the larger pattern is suspect;
- the conventional alternative;
- what could be deleted or simplified by correcting the root;
- the migration or compatibility risk.

Explicitly identify any chain resembling:

> Decision A required workaround B, which required abstraction C, which required special case D, whose existence is now being used to justify A.

These loops are high-priority findings.

## Evidence requirements

Every finding must include:

- severity: critical, high, medium, or low;
- confidence: high, medium, or speculative;
- concrete file and symbol references;
- the relevant behavior or diff evidence;
- the violated invariant, convention, or architectural expectation;
- whether it predates this change or was introduced by it;
- whether it is a root cause or downstream symptom.

Do not manufacture findings to fill categories.

Do not call something nonidiomatic without naming the more conventional alternative and supporting the comparison.

## Required output

Produce:

### 1. Executive assessment

A direct appraisal of whether the change is:

- fundamentally sound;
- sound but overcomplicated;
- locally correct but architecturally misframed;
- built on one or more faulty premises;
- too uncertain to integrate safely.

### 2. Intended-system model

Summarize what the implementation should conceptually look like, independently of the submitted code.

### 3. Change topology

Describe the major areas changed, new dependency directions, new abstractions, and highest-risk propagation paths.

### 4. Root-cause clusters

List systemic findings before local findings.

### 5. Suspiciously novel mechanisms

List constructs that would be surprising in a mature reference implementation and explain whether each is justified.

### 6. Findings ledger

Provide evidence-backed individual findings, grouped under their root cause.

### 7. What appears sound

Identify portions that should probably be retained so the audit does not become indiscriminate demolition.

### 8. Remediation strategy

Propose ordered remediation waves that correct premises before symptoms.

For each wave, identify:

- intended architectural correction;
- affected areas;
- behavior that must remain stable;
- tests or observations needed to prove equivalence;
- code likely to become deletable afterward.

### 9. Open uncertainties

State what cannot be concluded from the repository and what evidence would resolve it.

Stop after producing the audit. Do not edit files until the audit has been reviewed.
