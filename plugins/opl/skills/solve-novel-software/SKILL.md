---
name: solve-novel-software
description: Resolve uncertain feasibility, algorithms, protocols, or cross-system design before and during complex software implementation. Use when a wrong technical assumption could invalidate substantial work, or when correctness has no obvious test oracle.
---

# Solve novel software problems

Turn a technical uncertainty into evidence that supports an implementation
decision. This procedure complements the project's implementation workflow.
It does not require a new planning process for routine changes.

## Experiment willingly within a small budget

Treat user time, model usage, and review effort as constrained resources. Before
adding research, a probe, or another agent, name the decision it could change.
Prefer a local source read or an existing deterministic check when it answers
the question. Keep coupled work with one implementer; delegate only a bounded,
independent question that earns its coordination cost. Retain required review.

When a plausible idea can be tested cheaply and reversibly within the authorized
scope, try the smallest informative experiment without seeking certainty first.
State the hypothesis and stop condition. A negative result is useful evidence.
Anticipate likely needs from the stated goal and observed context; label those
predictions as assumptions and choose reversible steps that remain useful if
the prediction is wrong. Do not convert a prediction into an unrequested feature
or infer permission for costly, destructive, or external actions.

Do not default to repeated candidate generation, reviewer panels, benchmark
campaigns, or recurring self-improvement jobs. Preserve explicit budgets. If no
numeric budget exists, use the smallest sufficient check and reassess before
expanding it. After two failed repair cycles, revisit the premise and evidence
before another attempt. Do not weaken acceptance to save cost; report a material
verification gap when it cannot be resolved.

## Find the decision that matters

Identify the requested behavior and the constraint most likely to invalidate
the design. Distinguish a missing product decision from a technical question
that local inspection or an experiment can answer. Do useful independent work
while a product decision is pending.

Trace one representative input through the affected boundaries to its observable
result. Include state ownership, external dependencies, and the recovery path
where they affect the decision. Read the installed implementation and exact
dependency versions before relying on a remembered API.

Keep a short record of the active uncertainties in the project's existing task
notes. Use a local task artifact when the project has no suitable location.
For each uncertainty that changes the design, record:

- The claim and the decision that depends on it.
- The evidence already available and its limits.
- An observation that would contradict the claim.
- The smallest authorized check that can distinguish the plausible alternatives.

Rank uncertainties by the cost of being wrong, the amount of dependent work,
and the cost of obtaining useful evidence. Investigate the highest-impact
uncertainty that is practical to resolve. Do not use invented numerical scores
to make a qualitative judgment appear measured.

## Make an experiment change a decision

Compare the current approach with the strongest plausible simpler alternative.
For each, identify the assumption on which it depends. Before running a probe,
state what result would support, reject, or leave the assumption unresolved.
Choose the result threshold from the user's requirement or an existing contract.
If no threshold exists, characterize the behavior without claiming acceptance.

Use the actual runtime or boundary relevant to the question. A mock can check
the caller's behavior; it cannot establish an external system's semantics.
Bound the probe to the inputs, side effects, resources, and cleanup needed for
this decision. Use existing scratch conventions, and keep experimental code
out of production paths. Follow the applicable test and authorization rules.

Choose a correctness oracle before trusting the candidate. An oracle is an
independent basis for deciding whether a result is correct. When no trusted
expected output exists, read [references/oracles.md](references/oracles.md).

Capture the command or observation method, environment, relevant source state,
input, result, and limit of the inference. Include uncommitted changes when
identifying the source state; a commit identifier alone can be insufficient.
Keep credentials and private payloads out of task notes.

After a probe, update the decision. If the result is inconclusive, name the
remaining ambiguity and change the experiment accordingly. Stop a research
branch when further evidence would not change the implementation choice.
If the decisive experiment is unavailable, isolate the uncertain dependency
behind a reversible boundary and report the unverified assumption. Do not
substitute a fabricated success for missing evidence.

## Transfer findings into production

Record which contract the experiment supports, the conditions under which it
holds, and what would invalidate the finding. Carry those conditions into the
implementation plan. A successful experiment supports only the behavior and
environment it exercised.

Build the smallest usable path through the real components before expanding
the implementation. Check the boundary with the greatest uncertainty as soon
as that path can reach it. For parallel work, settle the shared contract first:
inputs, outputs, state ownership, error behavior, and who may change it. Follow
the existing delegation and independent-review rules.

Keep the experimental shortcut separate from the production decision. Use the
project's normal error handling, resource ownership, cancellation, and recovery
conventions where they apply. Inspect consumers when changing a contract; local
success does not establish compatibility for other callers.

Select verification from the actual failure modes. Use existing checks first.
Add durable tests only when the governing test and change-discipline rules permit
them. A one-time probe can answer a question without adding a permanent guard.
After the final relevant edit, verify the integrated behavior against the
original acceptance conditions and obtain required independent review.

## Remove residue from the current change

During the normal final diff review, connect each new abstraction, dependency,
fallback, configuration option, and helper to a current requirement or an
observed constraint. Inspect new branches for abandoned hypotheses and temporary
workarounds. Remove task-owned residue whose lack of purpose is established;
preserve unrelated work and follow the existing cleanup rules.

If extending the code needs another special case, check whether the current
representation still fits the requirement before adding it. Prefer a supported
framework mechanism over a custom substitute when it satisfies the contract.
Do not make code shorter by concealing state transitions, removing required
recovery, or weakening tests. Passing tests and low line counts do not by
themselves establish maintainability.

Use one scoped independent review where required, with evidence for concrete
defects rather than a general quality score. Recheck fixes and affected behavior.
Once acceptance checks and required review are satisfied, stop optional critique
and polishing unless new evidence identifies a problem.

## Preserve what the next session needs

Update one existing task record at decision boundaries and before handoff.
Keep it small enough to read before resuming work. Record the accepted outcome,
constraints, current decision and rejected alternative, evidence locations,
remaining uncertainties, owned work, and next useful action.

Tie completed checks to the state they checked. If code, dependencies,
configuration, or relevant inputs change, identify the invalidated evidence
and rerun only the affected checks. Resume from the artifacts and current
repository state; a previous summary is a navigation aid, not fresh evidence.

Report implemented behavior, supporting evidence, and remaining limitations.
Distinguish a design that appears feasible from an integrated implementation
that passed its acceptance checks.

The research basis and limits are in
[references/evidence.md](references/evidence.md). Read it when revising this
procedure or evaluating its claims, not on every implementation task.
