---
name: consensus
description: Examine a question with 2–3 independent perspectives and a reusable judge, with bounded disagreement, evidence and abstention.
---

# Consensus

Accept a question or description, plus any evidence and constraints. Produce a
supported answer, a qualified recommendation, or an explicit unresolved result.
This is a reasoning workflow; its result grants no implementation or external
action authority.

## Frame and budget

Keep the original question visible. Explore plausible, meaningful interpretations
before narrowing. Treat examples as seeds, not a closed list of capabilities or
outcomes. Distinguish rough directions from precise constraints; do not turn
imprecise wording into an invented optimization rule. Separate stated requirements
from inferred possibilities. An answer may retain several compatible supported
interpretations; do not force a unique winner. Keep assumptions and preferred
answers from the proposer open to challenge.

Choose two perspectives with distinct concerns, assumptions and evidence needs.
For question-specific selection, add a third only when a consequential part of
the question remains uncovered. The software-planning preset below uses three.
Describe each perspective for this question in its assignment; use existing host
roles as carriers rather than creating profiles or a permanent taxonomy. Every
perspective may reject the frame, identify a missing goal or propose another
option. Explain what each perspective covers and where overlap remains.

Set the budget before dispatch: two perspectives and one judge by default;
at most two rounds total. This permits at most six worker turns, or eight with
three perspectives. Keep initial perspective answers within 200 words, targeted
replies within 150 words and judge answers within 250 words. Honor a smaller
user or host budget. Reuse these workers within the question; add no nested panel,
model sweep or automatic CLI fallback.

Use authorized native delegation with fresh initial contexts. Give each worker
the original question, governing constraints, source references and its assigned
concern. Keep initial peer answers and the preferred conclusion from the coordinator
out of its context. Assign read-only work and no descendants. If two isolated
perspectives and a judge cannot be obtained within host permissions and capacity,
return `abstain` with the unavailable capability. Do not simulate their agreement
in one conversation.

## Optional software-planning preset

When requested, use the consensus-rnd planning concerns as three perspective
assignments and one meta-judge. This preset does not replace the default two
question-specific perspectives. Describe the roles for the actual question:

- **Minimal:** Find the smallest viable change that satisfies the full requested
  outcome. Question unnecessary scope and complexity; do not reduce the requested
  ambition to make the plan smaller.
- **Structural:** Check contracts, ownership, architecture and long-term
  maintainability. Accept additional implementation work when it produces a
  justified structural benefit.
- **Delete:** Challenge the necessity of proposed mechanisms. Prefer removal or
  collapse when the full requested outcome remains achievable. If a mechanism
  must stay, say so and abstain from a deletion proposal.
- **Meta-judge:** Compare the three independent plans under the reusable judge
  instructions below. Preserve unresolved objections and permission limits.

Use existing host roles as carriers; create no profiles. Host capacity and the
declared budget govern execution. Report when the full preset is unavailable;
do not silently claim its coverage. The same two-round limit applies, with at
most eight worker turns. A planning verdict grants no implementation authority.

## Independent answers

Ask each perspective to return:

- Its interpretation and any rejected assumption or missing goal.
- An answer or option, including the strongest relevant alternative.
- Decisive evidence with source references; label assumptions and missing facts.
- Its strongest objection and what evidence or value choice would change its
  answer. Return `abstain` when it cannot support a responsible conclusion.

Collect completed answers before showing any peer conclusions. Missing or failed
workers are not votes. Different perspectives can share model blind spots;
isolation does not establish statistical independence or calibrated confidence.

## Reusable judge

Give one separate judge the question, constraints, evidence references and compact
perspective answers. Reuse this judge for the second round with the changed
evidence and replies. Use this role instruction:

> Judge the answers against the actual question and evidence, not the number of
> votes, role prestige or the proposer's preference. Check whether the shared
> frame omitted a plausible consequential interpretation. You may reject that
> frame. Separate factual disagreement, value tradeoffs and permission limits.
> Resolve an objection only when evidence or an explicit choice answers it;
> preserve the strongest unresolved objection and all abstentions. Do not invent
> a compromise that loses a required outcome. Return a verdict, concrete answer
> if supported, decisive evidence, unresolved issues and the smallest next check
> or human decision that could change the answer.

Use these verdicts:

- `consensus`: at least two isolated contributors support the same concrete
  answer, and no assigned perspective leaves a consequential objection or
  missing premise unresolved. State who agrees and who abstains.
- `recommendation`: the judge supports an answer, but agreement is incomplete.
  State the disagreement; do not relabel a judge selection as consensus.
- `unresolved`: a missing fact, framing gap or value choice could change the
  answer. Name it and the useful next check or decision.
- `abstain`: independent participation or evidence is insufficient for a
  responsible answer. State what is unavailable.

The judge can recommend a new synthesis, but cannot claim that contributors
accepted an answer they did not assess. Agreement is neither evidence of truth
nor permission to act.

## One disagreement round

Stop after the first judge answer when no consequential issue remains, or when
another round has no useful evidence or clarification to examine. Otherwise send
only the specific open issue from the judge, relevant peer conclusions and new evidence
to the affected perspectives. Ask for a revision or a reason to retain their
answer; do not demand agreement. Give the completed replies to the same judge.

Stop after the second judge answer. Do not restart the panel to manufacture
convergence. If further work is needed, return its purpose and cost as a proposed
next step under normal host permission rules.

## Return

Lead with the answer and verdict. Include the selected perspectives, decisive
source references, material dissent or abstention, assumptions and remaining
uncertainty. State rounds and worker turns used. Retain compact conclusions in
the existing task record; keep raw transcripts out of the answer. Report any
independence or verification limitation. Leave implementation and approval to
the owning workflow.
