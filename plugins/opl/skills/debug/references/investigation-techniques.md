# Investigation techniques

Read the section that addresses the current evidence gap. Choose probes by the
question they answer and the available environment, not a fixed tool order.

## Construct a useful reproduction

Start at a boundary that reaches the defect: a focused test, HTTP request, CLI
with fixture input, or browser interaction with an assertion on the failing
state. A temporary harness can isolate a service or state transition, provided
its substitutes preserve the suspected mechanism. Preserve a real failing input
before simplifying it, and verify the same symptom after each reduction.

Other ways to expose the mechanism:

- **Replay:** feed a redacted captured request, event sequence, or trace into
  the relevant path. Preserve ordering and state when they affect the result.
- **Differential runs:** compare the same input and controlled environment
  across known working/failing versions or configurations. Identify confounding
  differences before attributing causality.
- **Bisection:** use a symptom-specific check between known good and bad commits,
  inputs, or dependency versions. Isolate revision changes from the user's work;
  classify build/setup failures separately instead of calling them bug failures.
- **Property or fuzz probes:** state the violated invariant, generate bounded
  inputs, and retain seeds and failing cases so discoveries are replayable.

Speed up setup or narrow the workload when that preserves the failure. A slower
representative experiment is more useful than a fast check of the wrong path.

## Intermittent or production-only failures

Record attempts, failures, exposure duration, and relevant load or timing for
each condition. Seeds, controlled clocks, isolated state, concurrency barriers,
or targeted stress can make a race easier to observe. Timing changes also alter
the system: confirm that an induced failure matches the original trace.

Compare failing and successful traces at candidate boundaries. For example,
correlate request IDs with task scheduling and state transitions rather than
collecting unrestricted payload logs. Choose a bounded experiment that can
separate the leading hypotheses. There is no universal required reproduction
rate, and zero failures in a small sample does not establish a fix.

When access is restricted, use existing evidence to narrow explanations and
specify what would falsify each. Request only the needed redacted artifact or
authorized observation. Production instrumentation remains subject to the
user's environment permissions; inability to add it does not prevent local
reasoning or a candid diagnosis with limits.

## Performance regressions

Define the regressed metric and representative workload before changing code:
latency distribution, throughput, memory growth, query count, or another
user-visible measure. Record input size, concurrency, warm/cold state, versions,
and measurement duration. Compare a known baseline under equivalent conditions;
separate setup cost and measurement noise from the relevant work.

Use a profiler, query plan, allocation trace, or targeted timing to locate the
cost. Broad logging can distort timing and expose data. Bisection or differential
runs can narrow the change, but still explain its mechanism before fixing it.
Do not require a minutes-long workload to become seconds-long before reasoning.

After the change, repeat the original workload. Use deterministic protection for
the underlying mechanism when useful (such as bounded query count or allocation
growth) and retain a representative measurement for the user's actual symptom.
Avoid brittle wall-clock assertions derived from one noisy run.

## Human-operated observations

If a device, sign-in, or interaction requires the user, provide a small sequence
with a clear expected/observed result and timestamps or correlation IDs. Keep
sign-in and credentials with the user. Record only the necessary observations,
then choose the next discriminating step. A shell script is optional; use the
environment's natural interaction channel instead of assuming a shared terminal.
