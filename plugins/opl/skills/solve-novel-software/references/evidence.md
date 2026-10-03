# Evidence and limits

Reviewed on 2026-10-02 (America/Chicago). This is a bounded review of primary
research and an engineering report, not a systematic review. The resulting
procedure is an engineering judgment. It has not been shown to improve this
user's development speed or cost.

## Residual edits are a concrete cleanup target

[TRIM, July 2026](https://arxiv.org/abs/2607.18161) attributes unnecessary
patch content to speculative and abandoned edits retained during agent search.
Its trajectory-minimization method reports a 17.9%--32.9% reduction in its
CodeSlop measure with negligible performance regression, at roughly half the
validation cost of its delta-debugging baselines.

This supports inspecting abandoned edits. It does not establish the same gain
for a manual diff review. The local procedure adopts that narrow inspection;
it does not install TRIM or run repeated trajectory minimization.

## Quality prompting is insufficient

[SlopCodeBench v2, May 2026](https://arxiv.org/html/2603.24755v2) evaluates
iterative extension across 36 problems and 196 checkpoints in Python. Its
quality prompts improve initial metrics but do not prevent later degradation;
the paper reports an average 12.1% increase in cost per checkpoint for the
prompting techniques studied. Its verbosity and structural-erosion measures
are proxies, not complete measures of maintainability or user value.

The local implication is to inspect the actual changed representation and
residual edits, not to rely on a longer cleanliness prompt or optimize a
line-count score. This inference is not a measured treatment from that study.

## Test volume is not the same as useful verification

[Rethinking the Value of Agent-Generated Tests, v2, April 2026](https://arxiv.org/html/2602.07900v2)
studies SWE-bench Verified with a lightweight agent scaffold. Prompting agents
to change test-writing volume did not significantly change final outcomes in
that setting, while changing process and cost. The authors also describe the
risk of tests embedding incorrect assumptions or expected results.

This supports selecting checks for the evidence they provide. It does not show
that tests are unnecessary or justify skipping required regression checks.
Independent expected behavior, existing tests, and the affected user-visible
path remain the basis for acceptance.

## Instruction overhead has mixed evidence

[Evaluating AGENTS.md, February 2026](https://arxiv.org/abs/2602.11988)
finds that context files can reduce success while increasing inference cost by
more than 20% in its settings. A different study,
[On the Impact of AGENTS.md, January 2026](https://arxiv.org/abs/2601.20404),
reports lower median runtime and output-token use over 124 pull requests in
10 repositories. These are different experiments; neither proves the effect
of this user's global instructions.

The local choice is a compact addition with optional detail. Existing user
requirements remain intact. No improvement is claimed from its word count,
and no extra invocation tests are introduced.

## Expensive harness demonstrations are not budget targets

[Anthropic's harness report, March 2026](https://www.anthropic.com/engineering/harness-design-long-running-apps)
includes a six-hour, $200 run compared with a 20-minute, $9 solo run. It also
describes reducing orchestration as model capability improved and making
evaluator use depend on the task. These are engineering examples, not a
controlled cost-benefit result for this user.

The procedure keeps ordinary work local, scopes required review, and avoids
open-ended generator/evaluator loops. Spend, latency, rework, and actual
acceptance evidence matter together; a polished demo alone is insufficient.

## What remains unmeasured

No paid service, model setting, automatic learning job, or background benchmark
is part of this change. File validation and document review can establish that
the files are consistent and usable. A small authorized capability smoke test
can expose a practical defect. Neither establishes a comparative productivity
gain. Future assessment should use authorized real tasks and record acceptance,
rework, elapsed time, and model usage when available. Any comparative AI
experiment needs explicit authorization and a finite budget.
