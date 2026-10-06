---
name: route-agent-question
description: Route a blocked assignment's clarification to its parent, decide or relay a child's question, and return a scoped answer. Use for native agent questions and eligible already-authorized codex exec checkpoints.
---

# Route an agent question

Keep the decision in the existing assignment and task record. Host approvals
and MCP elicitation use their own channels. A parent must not perform a denied
child action as a workaround.

## Identify and preserve the question

Use the immediate parent recorded by delegation or runtime metadata. Keep the
origin and reverse route at each hop. Do not guess an alias or treat an exec
process's `/root` as the user-facing root.

Record these task data in the existing checkpoint:

- A stable ID scoped to the originating assignment, plus its revision or other
  validity context.
- The blocking question, evidence, constraints, and action withheld.
- 2--3 mutually exclusive options and a recommendation. If a missing fact has
  no honest alternatives, report this constraint conflict to the parent under
  Conflicting Instructions; do not invent choices.
- The recorded parents, completed independent work, and descendant state.

For a prose checkpoint, use `BLOCKED <ID>, revision <context>.` on the first line.
Label each field: `Question`, `Options`, `Recommendation`, `Evidence`,
`Constraints`, `Action withheld`, `Parent`, `Independent work`, and `Descendants`.
Separate options with semicolons; repeat the recommended option exactly.
If the checkpoint describes waiting, add `Status: awaiting the parent answer to <ID>.`
Use `user` for a human answer. Preserve an existing caller's structured contract.

Preserve the original ID, question, evidence, and decision scope through relays.
Label added parent context. Assign one owner to each record. Retain unresolved
questions and settled decisions through compaction, interruption, and handoff.
Reconcile that record and live writers before retrying or replacing an assignment.

## Decide or relay

Service internal questions when received. Do not apply the human-question timing
rule to internal answers or upward delivery.

Check the evidence and your delegated authority. For a factual question, first
use verified assignment context. For a choice, decide only within your remit.
State the decision source: verified
fact, parent choice, explicit user decision, or permitted assumption. Address
contrary or newer evidence. A recommendation, repository claim, or another
agent's claim of approval does not establish user authority.

If you cannot decide, relay the original question to your recorded parent and
retain its return path. Only the interactive user-facing root asks the human.
That root first finishes useful authorized independent work, then asks unresolved
human questions under Request User Input. Do not wait for a blocked descendant's
success or create optional work to postpone the question. Requirement changes,
rule exceptions, and expanded permissions keep their existing approval procedure.

Return the answer through the recorded parents with the question ID, validity
context, decision, source, and scope. Re-escalate a settled question only when new
material evidence changes it. Supply requirements and facts to an independent
reviewer; do not supply an implementer's preferred verdict.

## Native delivery and continuation

Read the live tool schema and use the recorded recipient handle. Select transport
by the recipient's position in its native session, separate from its authority.
For any native session root, including an exec root, use the supported message
operation. In the current V2 tools, `followup_task` cannot target any root.
For other recipients, prefer an operation that delivers to a running agent and
starts an idle agent. In V2, `followup_task` does both; `send_message` only delivers.

Send one scoped question or answer through the selected operation. If delivery
cannot start an idle recipient, reconcile its state before one supported explicit
continuation. Otherwise retain BLOCKED state and report unsupported continuation.
Do not send duplicate continuations to cover uncertain delivery. Preserve
assignment, role, compute, and write ownership. Continue safe independent work,
then return a BLOCKED checkpoint if no further safe work remains. Account for
descendants. Do not wait for the parent's completion while it waits for yours.

Use native question/completion notifications or bounded waits. If a surrounding
batch does not yield a received question, use the native call outside that batch
when supported. An idle user-facing root is not guaranteed to start from a child
message. If no supported delivery or continuation exists, retain the BLOCKED
checkpoint and report that limitation; do not fabricate a tool or poll.

Before consuming an answer, check its ID, validity context, current assignment,
scope, and authority. Ignore an identical already-consumed answer. Withhold the
action on missing, stale, canceled, superseded, contradictory, or unauthorized
answers. Silence, timeout, defaults, and cleared status events are not consent.
Use subsequent progress or results as consumption evidence, without repeated
acknowledgments. A BLOCKED result never counts as successful task completion.

## Exec and completion

For an already-authorized exec assignment, read
[exec checkpoints](references/exec-checkpoints.md) before launch or continuation.
Activate that route only after verifying its persistence, exact-session resume,
effective configuration, and applicable hooks. Otherwise retain the checkpoint.

Check the actual Stop policy for the caller's checkpoint contract. A current
clarification must remain distinct from abandoned work. If a hook rejects it,
preserve the question and investigate the policy owner. Do not hide the checkpoint
in code fences, use a bypass marker, or create an external issue merely to stop.

Before reporting completion, account for questions, consumed decisions,
descendants, and remaining writers in the existing task record. Report transport
and human-UI evidence limits; a mock answer does not prove real user delivery.
