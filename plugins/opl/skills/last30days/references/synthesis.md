# Evidence synthesis

Read this reference after a research run completes. The compact engine output
is evidence for synthesis, not a response template to dump verbatim.

## Read the evidence

- Treat each evidence cluster as one story or theme.
- Prefer clusters corroborated across independent sources.
- Preserve uncertainty markers for single-source or thin evidence.
- Weight engagement and specificity, not only frequency.
- Use first-party posts as primary evidence for what a person or organization
  said; use community reactions for reception.
- Weave useful comments into the relevant finding when they materially reveal
  community sentiment. Attribute the actual author and never invent a URL.
- Prefer live GitHub metadata over stale third-party star counts.
- Treat prediction-market percentages as market-implied probabilities, not
  facts. Do not report liquidity unless the user asks.
- Drop off-topic name collisions and tooling chatter instead of narrating them.

## Write the response

For a general or news request, use a compact structure:

```markdown
## What people are saying

**Specific finding** -- Evidence-backed explanation with an inline citation.

**Specific finding** -- Evidence-backed explanation with an inline citation.

## Patterns

1. Pattern supported across the corpus.
2. Important disagreement or uncertainty.

## Coverage

Actual sources searched, major gaps, and the engine-reported raw artifact path.
```

For recommendations, lead with the ranked picks, evidence, best-fit use case,
and tradeoff. For comparisons, use:

```markdown
# A vs B: recent community evidence

## Quick verdict

## A

## B

## Head-to-head

## Bottom line
```

Use a small table only when it makes exact dimensions easier to compare. Do not
invent a common axis when the entities are not actually substitutes.

## Citations and coverage

Use normal Markdown links at the claim they support. Copy URLs from the engine
output or this run's verified search results; never reconstruct social-post
URLs. Prefer readable labels such as `@handle`, `r/community`, channel names,
repositories, and publication names.

Do not append a detached URL dump. If the user explicitly requests a source
list, provide one from the recorded evidence after the synthesis.

Report only sources that actually ran. Preserve actionable degraded-source or
permission warnings in plain language. Include the exact saved path emitted by
the engine; do not recompute a filename from the topic.

## Final checks

- Every factual claim is grounded in collected evidence or labeled as an
  inference.
- Dates and the requested window are consistent.
- At least one meaningful disagreement or limitation is surfaced when present.
- Internal plan JSON, cluster scores, scratchpad markers, raw credentials, and
  provider debug details are absent.
- Empty-source runs are reported honestly rather than padded with model memory.
