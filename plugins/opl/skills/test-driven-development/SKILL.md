---
name: test-driven-development
description: Use when implementing features, fixing bugs, refactoring executable behavior, or changing an observable contract that needs regression protection.
---

# Test-Driven Development

Use a tight evidence loop: specify one observable behavior, watch a test fail for
that behavior, make it pass with the smallest coherent change, then improve the
design while it stays green.

## Scope

Apply this skill to shipped behavior: features, bug fixes, behavioral
refactors, validation, edge cases, and executable configuration or scripts.

Tests are usually unnecessary for prose, static content, mechanical metadata,
or generated output whose generator already owns the behavior. A prototype is
outside this workflow only when the user has explicitly accepted throwaway
work. When uncertain, test the observable contract that could regress rather
than every function involved in producing it.

## Discover the Test Surface

Before the first test, inspect repository instructions, manifests, neighboring
tests, CI configuration, project domain vocabulary such as `CONTEXT.md`, and
applicable architecture decisions. Establish:

- the framework and local test conventions;
- the command for one focused test;
- the broader command that covers the affected behavior; and
- the caller-visible interface, domain language, and narrowest boundary that
  provide meaningful confidence.

Prefer checked-in wrappers and repository scripts. Do not substitute a familiar
command for the repository's actual workflow.

## The Loop

1. **Specify** -- Name the next caller-visible capability through its public
   interface and the realistic production break the test must catch.
2. **RED** -- Write the smallest test that demonstrates that behavior. Run the
   focused command and confirm an assertion fails because the behavior is absent
   or wrong. A syntax, import, fixture, or environment error is not RED; correct
   it until the test fails for the intended reason. A test that passes
   immediately establishes existing coverage, not test-first evidence.
3. **GREEN** -- Make the smallest coherent production change that satisfies the
   test. Run the focused command. Change the test only when the intended contract
   was wrong, not to accommodate an incorrect implementation.
4. **REFACTOR** -- Improve names, seams, duplication, and test clarity while the
   focused test remains green. Add no new behavior during this step.
5. Repeat with the next behavioral slice. Keep each cycle a vertical
   tracer-bullet through the relevant layers so the result of one cycle informs
   the next; do not batch all tests before all implementation.

After the last change that can affect results, run the affected broader suite
and the repository's required gates. Repeating an unchanged command adds no
evidence unless nondeterminism is itself under investigation.

## Protect Existing Work

Test-first order does not authorize deleting, overwriting, or reverting work.
Resolve ownership before rolling anything back.

- For an implementation created by the current agent during the current task,
  inspect the diff and restore only those owned edits when doing so is safe and
  useful for a genuine RED.
- For pre-existing, user-authored, shared, committed, or ambiguously owned code,
  preserve it. Add a characterization or regression test around the behavior
  being changed.
- If the corrected behavior already exists and the new test passes, report that
  the test was added after the implementation. Do not manufacture a failure or
  weaken the assertion.
- If the user explicitly directs a non-TDD path, follow their instruction and
  state what evidence or regression protection remains missing.

## Test Quality

Before writing or changing tests that use doubles, cross process or service
boundaries, depend on side effects, or calculate nontrivial expected values,
read [references/test-quality.md](references/test-quality.md).

For ordinary tests, keep these invariants:

- name scenarios as capabilities a caller or user cares about and exercise them
  through public interfaces;
- derive expected values independently of the code under test;
- use real collaborators when practical and mock the narrow slow, external, or
  nondeterministic boundary;
- keep state isolated and outcomes deterministic; and
- test the behavior at the lowest level that still catches the realistic break.

## When the Loop Resists

| Signal | Response |
| --- | --- |
| The test is hard to arrange | Treat the friction as interface-design feedback; simplify the public seam or choose a more natural boundary. |
| Everything must be mocked | Move the test outward or introduce a real dependency boundary. |
| The test passes first | Confirm the behavior already exists, then select the missing behavior or report tests-after honestly. |
| There is no test harness | Add the smallest project-compatible harness if in scope; otherwise report the blocker before implementation. |
| A manual check seems faster | Use it for diagnosis, then encode the regression as a repeatable test. |

## Completion Evidence

Before claiming the behavior complete, establish all of the following:

- each changed behavior has regression protection at an appropriate boundary;
- every test-first behavior was observed failing for the intended reason;
- focused tests pass after implementation and refactoring;
- affected broader checks pass after the final relevant change; and
- skipped, disabled, flaky, or unavailable checks are reported rather than
  hidden.
