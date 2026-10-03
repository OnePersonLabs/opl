# Choose an independent correctness oracle

Use the narrowest method that can reject a plausible wrong implementation.
These methods support different claims. Combine them only when they address
distinct risks, and follow the project's limits on adding tests.

| Uncertainty | Useful check | Limit |
| --- | --- | --- |
| An unfamiliar optimized algorithm | Compare small inputs against a simple exhaustive or independently derived reference. | Agreement on small inputs does not establish scaling or all-input correctness. |
| No complete set of expected outputs | Check a relation required by the domain, such as conservation or invariance under an irrelevant reordering. | A relation must follow from the contract. A wrong implementation can satisfy a weak relation. |
| A parser, serializer, or transformation | Use independent fixtures, invalid inputs, and an independent implementation where available. | A round trip can pass when both directions share the same defect. |
| A concurrent or retrying protocol | Model legal transitions and observe meaningful schedules, including a failure between an effect and its acknowledgement. | A few schedules do not prove all possible interleavings. |
| A performance constraint | Compare equivalent workloads, environments, and correctness results; measure the resource named in the requirement. | A faster incorrect result, changed workload, or isolated best run cannot establish the required improvement. |
| A remote API or package capability | Exercise the exact supported boundary with a minimal authorized request or local reproduction. | Documentation supports an intended contract; a mock does not prove the remote service follows it. |

For differential checks, establish why the reference is trustworthy for the
tested input range. Do not copy the candidate's algorithm into the reference
and treat agreement as independent evidence.

For properties, derive the relation from the user's domain or an authoritative
contract. Do not assume that operations commute, retries are idempotent, or
serialization is lossless merely because those properties would simplify the
implementation.

For failures, observe both the returned result and the resulting state when
the contract constrains side effects. A reported error can coexist with a
partially completed operation.

For benchmarks and intermittent failures, record the workload, exposure,
variation, and environment. Use enough observations for the decision's risk
and resource budget. Report uncertainty rather than inventing a confidence
claim from an insufficient sample.

When no decisive oracle is available, narrow the claim to the behavior that
can be observed. Keep the unresolved property explicit in the decision record.
