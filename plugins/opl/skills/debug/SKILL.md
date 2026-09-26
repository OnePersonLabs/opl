---
name: debug
description: Diagnose bugs, failing tests, build failures, performance regressions, and unexpected behavior; implement and verify a causal fix when requested. Use for concrete failures that need investigation, not general code review or speculative optimization.
---

# Debug

Connect the user's symptom to its cause, then fix the owning behavior when that
is within scope. A plausible explanation remains a hypothesis until evidence
distinguishes it from alternatives.

## Establish scope and evidence

Preserve diagnosis-only requests: investigate and report without changing
production behavior. Existing permission to fix includes the ordinary local
investigation and regression work needed to deliver it; do not ask again.
Temporary probes must respect the same edit and environment boundaries.

Read the relevant project instructions, test commands, context notes, and
architecture decisions. Capture the expected result, exact observed symptom,
complete relevant error, environment, and known trigger. Compare recent changes
and the nearest working scenario without treating correlation as proof.

## Investigate

1. **Choose a signal that catches this failure.** Prefer an existing failing
   test or a repeatable command through the real failing path. Assert the user's
   symptom, not merely that execution finished. Preserve the original scenario
   for final verification.
2. **Bound the failure.** Determine which inputs, state, callers, environments,
   or timing conditions matter. Reduce a reproduction one element at a time,
   checking that the same failure survives. Stop when further reduction would
   not help the next experiment; exhaustive minimality is not a prerequisite.
3. **Trace the first divergence.** Follow the wrong value or state transition
   through its callers and component boundaries. Observe only the boundaries
   needed to separate the remaining explanations.
4. **Test a falsifiable explanation.** State what causes the symptom, the
   evidence connecting them, and an observation that would disprove it. Rank
   alternatives when the evidence is ambiguous; test one active explanation
   with the smallest discriminating experiment, changing one factor at a time.
5. **Reconcile with the original evidence.** Discard contradicted hypotheses.
   A supported explanation must account for the original symptom and relevant
   working counterexamples. If probes keep failing, revisit the signal,
   assumptions, and ownership before adding more patches.

For difficult reproductions, intermittent failures, performance regressions, or
human-operated environments, read
[references/investigation-techniques.md](references/investigation-techniques.md).

A fast, deterministic, agent-runnable reproduction is useful, not a gate on
reasoning. When one is unavailable, continue with accessible logs, traces, code,
and controlled comparisons. Label hypotheses and missing evidence explicitly;
ask for the smallest observation or access that would distinguish them only
when progress depends on it. Do not invent a reproduction or claim certainty
because a plausible explanation is all that is available.

Keep secrets and private payloads out of commands, logs, and reports. Use
existing environment-based credentials and capture only the needed signal.

## Fix and verify when requested

- Put regression coverage at the narrowest boundary that reproduces the real
  failure pattern, including multiple callers, ordering, or state when those
  are causal. A shallow test that cannot expose the defect is not coverage.
  Use the recipient's `$test-driven-development` for the executable
  change: observe the defect fail, make the smallest coherent fix, and rerun.
- Change the layer that owns the violated contract. Do not accumulate
  downstream compensation unless recovery is that boundary's responsibility.
- If a test seam is missing, examine a realistic outer boundary or a small
  project-compatible harness. Treat test friction as evidence to investigate,
  not proof that the architecture is wrong. State any actual coverage limit.
- Rerun the original, unreduced scenario and affected checks after the final
  relevant change. For statistical failures, compare equivalent workloads and
  report exposure and observed failure rates; a clean run alone proves little.
- Remove probes and temporary artifacts you introduced unless they have an
  agreed durable purpose. Preserve pre-existing work. Recommend broader
  architectural change only when the investigation supports it.

Report the causal chain and distinguishing evidence, what changed (if anything),
original-symptom and regression results, and material uncertainty. Distinguish
observed facts, supported conclusions, and untested proposals. Never claim an
external cause without directly observing that boundary, or a working fix from
an unrelated passing check.
