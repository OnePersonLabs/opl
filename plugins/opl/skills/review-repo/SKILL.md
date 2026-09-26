---
name: review-repo
description: Use when reviewing large or agent-generated changes, unfamiliar repositories, major refactors, or working code that feels unusually complex, inconsistent, nonidiomatic, difficult to navigate, or difficult to explain; especially before integration or when local patterns may have become self-reinforcing.
---

# Auditing Repository Shape

## Overview

Audit whether a repository and its subsystems have the shape expected of a mature implementation of their requirements.

Do not merely ask whether each piece works or can be defended locally. Reconstruct the expected system independently, compare the observed system against it, and investigate unexplained deviations.

**Core principle: Locally reasonable code can form a globally unreasonable system.**

## Audit Mode

This is a cold, read-only audit.

- Do not edit files.
- Do not inherit or defend the implementing agent's reasoning.
- Treat the current repository as evidence, not authority.
- Compare against the appropriate baseline when available.
- Passing tests establish limited behavioral evidence, not architectural correctness.
- Repetition establishes prevalence, not legitimacy.

Use isolated subagents or independent passes when available. Give reviewers the requirements, baseline, diff, and repository, but not the implementation conversation or other reviewers' conclusions.

## 1. Establish Ground Truth

Identify:

- the intended behavior and constraints;
- the baseline commit or pre-change state;
- the complete changed surface;
- deliberate conventions that clearly predate the change;
- frameworks, platforms, languages, and tools that define the relevant reference classes.

Separate:

1. domain necessities;
2. platform necessities;
3. intentional repository conventions;
4. transitional compatibility;
5. legacy accidents;
6. mechanisms introduced by the current change.

## 2. Reconstruct the Expected Shape

Before closely interpreting the implementation, independently model:

- the essential domain concepts and invariants;
- responsibility and ownership boundaries;
- dependency direction;
- lifecycle and state ownership;
- expected public and developer-facing interfaces;
- conventional framework and platform primitives;
- the simplest mature architecture that could satisfy the requirements.

Ask:

- What would normally exist?
- What would normally own this responsibility?
- What vocabulary and structure would make the system predictable?
- What would be surprising to find in a mature reference implementation?
- What machinery would likely be unnecessary?

Do not derive the expected model from the current implementation.

## 3. Audit at Multiple Scales

Inspect the repository, each subsystem, and each important interface.

### Architecture and ownership

Check responsibility placement, module boundaries, dependency direction, duplicated ownership, cross-layer coordination, and abstractions that know too much.

### Human-facing and machine-facing surfaces

Treat all interaction surfaces as designed interfaces, including:

- APIs and exported types;
- commands and scripts;
- configuration and environment variables;
- schemas and events;
- routes and entry points;
- directory and package structure;
- CI jobs and operational workflows;
- naming systems and documentation.

For each surface, determine whether:

- peers follow a predictable grammar;
- names communicate scope, strength, ownership, and effects;
- distinct terms represent distinct contracts;
- synonyms or aliases add real value;
- broad names hide narrow behavior;
- internal details leak into higher-level interfaces;
- a root or public surface unnecessarily proxies implementation details;
- a new maintainer could predict how to perform an analogous operation.

Incoherent vocabulary is often evidence that features were named episode by episode rather than designed as one system.

### Framework and ecosystem fit

Identify custom mechanisms that duplicate, bypass, or fight:

- language facilities;
- framework primitives;
- package-manager or build-tool capabilities;
- platform lifecycle mechanisms;
- standard configuration;
- established ecosystem conventions.

Research current official documentation and maintained reference implementations when the expected approach is uncertain.

Search for how mature systems solve the underlying requirement, not how to improve the local workaround.

### Causal complexity

Trace why each new abstraction, wrapper, adapter, flag, cache, queue, synchronizer, validator, compatibility layer, exceptional path, and orchestration script exists.

Classify it as:

- intrinsic to the domain;
- required by a platform boundary;
- deliberately conventional;
- temporary migration support;
- compensation for another local decision;
- unclear.

Investigate anything whose justification depends primarily on another mechanism introduced by the same change.

Look for loops such as:

> Decision A required workaround B, which required abstraction C, whose existence is now used to justify Decision A.

### Behavioral and lifecycle integrity

Trace important flows end to end:

- initialization and shutdown;
- ownership transfers;
- state transitions;
- concurrency and cancellation;
- retries and failure behavior;
- persistence and recovery;
- resource acquisition and cleanup;
- error propagation;
- platform-specific boundaries.

### Contract integrity

Determine whether tests, types, schemas, mocks, comments, and documentation enforce the intended behavior or merely memorialize the implementation.

Look for:

- tests coupled to incidental mechanisms;
- mocks that bypass the risk being tested;
- interfaces changed to accommodate an implementation;
- documentation that retroactively declares an accidental pattern intentional;
- validators that prove internal consistency without proving correctness.

### Simplicity and deletion

Ask what could disappear if the correct:

- abstraction;
- ownership boundary;
- data model;
- framework primitive;
- command surface;
- lifecycle;
- package structure

were used.

Prefer removing a false premise over polishing its consequences.

## 4. Use Absence as Evidence

When a substantial local mechanism appears unusual:

1. Name the underlying problem without referencing the mechanism.
2. Inspect current official guidance.
3. Inspect several mature implementations in the correct reference class.
4. Determine how they solve the requirement.
5. Check whether they need an equivalent mechanism.
6. Explain the difference.

Absence is a reason to investigate, not automatic proof of error.

A novel mechanism may be justified by unusual domain constraints. Require the repository to make that justification visible and testable.

## 5. Build a Novelty Ledger

Record mechanisms, conventions, or structures that are:

- newly introduced;
- unusually elaborate;
- difficult to name using standard vocabulary;
- absent from mature reference implementations;
- spread across many files;
- responsible for new exceptions or aliases;
- necessary only because another new mechanism exists.

For each, state:

- the requirement it serves;
- why conventional approaches are insufficient;
- evidence supporting that claim;
- its downstream complexity;
- what would become removable if it disappeared.

## 6. Compress Findings to Root Causes

Do not report a swarm of symptoms independently.

Cluster findings by originating assumption or design decision. Identify:

- the root premise;
- the affected files and subsystems;
- downstream machinery it forced into existence;
- why the result appears locally reasonable;
- why the overall shape is suspect;
- the conventional alternative;
- the expected deletion or simplification radius;
- migration and behavioral risks.

A useful audit reduces many oddities to a small number of causal explanations.

## Evidence Standard

Every finding must include:

- severity: critical, high, medium, or low;
- confidence: high, medium, or speculative;
- concrete file and symbol references;
- observed evidence;
- the expected invariant, convention, or shape;
- whether it predates or was introduced by the reviewed change;
- whether it is a root cause or symptom;
- the conventional alternative or unresolved research question.

Do not produce findings merely to fill categories.

Do not label something nonidiomatic without identifying the relevant convention.

Do not recommend replacing unusual code solely because it is unusual.

## Required Output

### Executive assessment

Classify the change or repository as:

- fundamentally sound;
- sound but unnecessarily complex;
- locally correct but globally incoherent;
- built on faulty premises;
- too uncertain to integrate safely.

### Intended-system model

Describe the expected conceptual architecture independently of the implementation.

### Change topology

Summarize changed areas, dependency shifts, new mechanisms, public surfaces, and propagation paths.

### Root-cause clusters

Present systemic causes before local symptoms.

### Surface coherence

Assess whether APIs, commands, configuration, structure, naming, and operational workflows form predictable systems.

### Novelty ledger

List suspiciously novel mechanisms and whether each appears justified.

### Findings ledger

Provide evidence-backed findings grouped under their causes.

### What appears sound

Identify code and decisions that should probably remain.

### Remediation waves

Order corrections so premises are fixed before symptoms. For each wave state:

- intended correction;
- affected areas;
- behavior that must remain stable;
- evidence required;
- code likely to become removable.

### Open uncertainties

State what cannot yet be concluded and what evidence would resolve it.

Stop after the audit. Do not implement remediation until the findings have been independently reviewed.

## Maintainer Verification

This skill has behavioral evaluation scenarios in `references/TESTS.md`.

When creating or modifying this skill, run those scenarios using isolated agents:

1. Run each scenario without the proposed skill and record the baseline failure.
2. Run it again with the skill loaded.
3. Confirm the agent meets the stated success criteria.
4. Add new scenarios for any rationalizations or blind spots discovered.

`TESTS.md` is for skill development and regression testing. It is not part of the repository audit workflow.
