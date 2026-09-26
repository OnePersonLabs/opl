# Test Quality

Load this reference when a test uses doubles, crosses a process or service
boundary, depends on side effects, or calculates nontrivial expected values.

## Name the Break

Before writing the body, state the realistic production mutation that should
make the test fail: a wrong branch, missing side effect, malformed payload,
incorrect boundary value, unauthorized path, or broken contract. If only an
intentional rewrite of private structure or wording can fail the test, move the
assertion to the behavior that depends on that decision.

Use a final mutation check: mentally replace the result with an empty value,
choose the wrong branch, omit the side effect, or corrupt a boundary argument.
At least one relevant test should fail for each realistic defect.

## Choose the Confidence Boundary

Choose test scope by the failure being guarded, not a fixed unit/integration/E2E
ratio:

- Pure deterministic policy can usually be tested at a small boundary.
- Serialization, persistence, filesystem, process, or API contracts usually
  need an integration boundary containing the real adapter.
- A critical user journey may justify an end-to-end test when lower layers
  cannot prove that the assembled system works.

Use the lowest boundary that still contains the components whose interaction
could realistically break. Moving lower than that produces fast but false
confidence; moving higher adds cost and failure noise without necessarily
adding evidence.

## Derive Expectations Independently

Expected values must not reuse the code, builder, parser, query, constant, or
algorithm under test. Prefer hand-checked literals, independently constructed
fixtures, or a simpler oracle. A shared implementation on both sides of an
assertion can make the test tautological.

Test behavior that depends on constants rather than the constants themselves.
Test scripts and generated artifacts by running them against controlled inputs,
not by searching their source for required wording.

## Use Doubles Deliberately

Start with the real collaborator when it is deterministic, local, and cheap.
Before replacing it, list its relevant side effects and keep the layer that owns
those effects real. Replace the narrow boundary that is slow, external,
destructive, unavailable, or intentionally nondeterministic.

A useful double must:

- mirror the complete data shape the production boundary promises;
- distinguish success, failure, malformed, and edge-case branches;
- reject unexpected arguments when arguments are part of the contract; and
- support assertions on the real component's outcome.

Call count or ordering assertions are appropriate only when retries, batching,
idempotency, sequencing, or another interaction is itself observable contract
behavior. An assertion that merely proves a mock was rendered or called does
not protect production behavior.

When mock setup dominates the scenario, move to a test with real components or
improve the production seam. When a production boundary is warranted, prefer
specific typed operations over a generic fetch or execute interface that forces
conditional logic into test doubles. Test-only cleanup belongs in test support
unless the production component genuinely owns that resource lifecycle.

## Keep Tests Legible and Stable

Favor descriptive, self-contained scenarios over abstraction introduced only
to remove a few repeated lines. Extract helpers when they express domain setup
or remove irrelevant mechanics; keep the decisive inputs and expected outcomes
visible in the test.

Control time, randomness, ordering, shared state, and external availability at
their owning boundaries. A flaky test is an unresolved behavior or isolation
problem, not evidence to average across retries.

Snapshots are appropriate when the complete representation is the reviewed
contract. Prefer targeted assertions when large snapshots would hide the
meaningful change.

## Brownfield Tests

For legacy behavior, first decide whether the current result is a contract to
preserve or a defect to change:

- A characterization test records behavior that must remain stable during a
  refactor.
- A regression test demonstrates a known defect and must fail before its fix.
- A test added after already-correct implementation still provides protection,
  but it is not evidence that the implementation was test-driven.

Do not create a false RED by asserting a behavior nobody wants or by temporarily
damaging shared code.

## Review Gate

Before accepting a changed test, answer:

1. What realistic production defect does it catch?
2. Is the expected result independent of the implementation?
3. Does the selected boundary contain the risky interaction?
4. Are doubles narrower than the behavior under test and faithful to reality?
5. Would the test remain useful after an internal refactor?
6. Can it run deterministically and in isolation?

If any answer is unclear, improve the scenario or choose a better boundary
before treating the test as regression evidence.
