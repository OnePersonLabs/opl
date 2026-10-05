---
name: human-collaboration
description: Involve the human in consequential parallel work through a durable prioritized inbox. Use for architectural, pattern, algorithmic or strategic review, grounded experiments, human-initiated contributions, and recovery or disposition of submitted feedback. Keep ordinary approvals and rule exceptions on their required channels.
---

# Human collaboration

The root prepares useful human contributions, continues independent work, and
integrates the responses. This is not an approval queue, a substitute for agent
review, or a way to occupy the user while agents work.

## Enter and recover

Resolve this loaded skill directory. Use its `scripts/human.py` with Python 3.11
or newer (`python` on Windows, `python3` on POSIX; honor `PYTHON_BIN`). Do not copy
the helper into the project. All global options precede the command:

```text
<python> -B -X utf8 <skill>/scripts/human.py --workspace <project> --thread <root-id> <command>
```

Use the known root thread ID or `CODEX_THREAD_ID`; never guess it. `init` creates
`.human/` and binds that root. It does not start a server or contact Codex. If an
inbox exists, use `pending` and `list` before creating more work. Inspect only the
relevant full items with `show H006`. Recheck pending input after startup,
resumption or compaction, before related commitments, and before completion.

One root owns intake and disposition. Workers propose contributions to their
parent; they do not publish assignments or start their own inboxes. A different
root must inspect the current owner and use `bind --reason` for an explicit
handoff. Binding never resets claims or replays implementation effects.

## Select and prepare

Choose work where this particular person's contribution can improve a decision,
reduce meaningful uncertainty, or produce useful evidence. Include technical
judgment and invention, not only preferences, approval, or testing. Match their
available context, device, instruments, and interest. No worthwhile assignment
is a valid outcome. Do not manufacture busywork or delegate supervision of agent
failures.

Keep one active assignment by default, with three ordinary ready recommendations.
The index retains the rest under Later; blockers and drafts remain visible.
Priority is 0--100, lower first. Rank by consequence, likely value of human input,
and how soon commitment becomes expensive, balanced against human effort. Write
a concrete `why_now`, not an unexplained score. Top position is a recommendation,
not evidence that the human has started. Review the queue at planning boundaries:
combine overlapping questions, defer unsuitable work with reasons, and retire
obsolete items without deleting their history. Never retire an active item,
draft, or unanswered submission. Prepare candidate briefs only when justified;
do not generate a backlog of speculative two-page documents.

Maintain consequential decisions with `decision: true`, including choices the
agents consider settled. Stable H-numbers do not change with rank. Accept a
challenge to any decision; silence is not agreement. Preserve meaningful
alternatives, uncertainties and reopening assumptions in the existing project
records rather than making a competing architecture database.

## Technical review briefs

Prepare one coherent 1--2-page review, not a compressed dump of the entire system.
Human-friendly means context-complete, not technically shallow. Include:

- The decision, its downstream consumer, why it matters now, and what work can
  continue without the answer. Distinguish a genuine blocker from an invitation.
- Grounded context: current versus proposed behavior, requirements, ownership,
  invariants, and the exact source snapshot. Explain internal terms locally.
- A mechanism-revealing diagram and concrete worked case. Show data/ownership
  flow for architecture, actual uses for patterns, or inputs/outputs, compact
  pseudocode and a troublesome trace for algorithms.
- The recommendation and strongest practical alternative, including doing less
  or postponing an abstraction. State the deciding tradeoff and reversal test.
- Evidence versus assumptions, relevant source references, an explicit invitation
  to challenge/reframe, and an easy return path. No diagnosis or formal report
  should be required from the human.

Use `publish` with a JSON spec (file or stdin `-`); see
[the protocol and examples](references/protocol.md). Capture only relevant
workspace-relative `sources`, never credentials or unrelated private files.
SVG/PNG/JPEG diagrams in the source snapshot render in the phone reader. Use
`![caption](source:0)` for the first source, or the workspace-relative path.
Plain Markdown stays usable in an editor. The small reader does not execute HTML
or render Mermaid; export a diagram image for the phone instead of promising a
renderer that is not present.

Published briefs end in `# Reply`. Never rewrite that file after publishing.
`revise` creates a new numbered revision when no current human work is in flight;
retain older versions. Do not silently retarget input to newer source.

## Respond and integrate

Saving a file or phone draft is not submission. The human explicitly uses Send
or `submit H006` for the Markdown reply. `submit --revision` targets an older
brief. The helper stores actual filesystem nanosecond modification stamps after
publishing, observes later stamps, and compares content. Timestamps are hints,
not the message protocol. File and phone drafts are separate; neither silently
overwrites the other.

Submissions leave Needs you immediately and remain With agent until addressed.
Use `claim <submission-id>` before applying feedback. Inspect its reviewed
revision and source drift, its existing claim, and any recorded outcome. A
repeated receipt is not another instruction to make the same code change.
`claimed_now: false` requires reconciling existing work and checkpoints, not
blind replay. Exactly-once external code effects cannot be guaranteed by an
inbox database.

Interpret the contribution in context. Identify affected decisions, dependencies
and current evidence. Preserve required approval and exception procedures; no
submission or status confers additional permissions. Continue independent work;
coordinate any work that would entrench a challenged choice. Do not treat a
human design preference as a passing runtime check or as a universal user need.

After integration, record `outcome <submission-id> <result.json>` with the actual
change or reason not adopted, relevant evidence pointers, and an explicit
`source_review`. Use `explained` for an answer that returns the item to the human,
or `follow_up` for a remaining question. Both stay in the same conversation.
Unresolved later responses keep the item With agent. Root handoffs must preserve
partly applied work in the existing task checkpoint before changing ownership.

For Projector projects, put accepted meaning, reasons, alternatives and evidence
in Projector's existing documents/checkpoint. Link them from the outcome. OPL and
the native host own scheduling; Projector does not become a second coordinator.

The human may start a contribution in the phone interface or with `contribute`.
Establish its context before promoting it to a product decision. A human does not
need an agent's invitation to question the architecture.

## Delivery and phone access

The session hooks report outstanding submissions only to the bound root. They
are inactive without a project inbox, do not initialize one, do not invoke a
model, and never block Stop. `PostToolUse` deduplicates notices; startup/resume,
new user turns and Stop re-surface unresolved work. Notifications are not claims.

`serve` runs a foreground local web service on `127.0.0.1:8766` by default. Report
its pairing link only after it starts. The link contains a bearer token; keep it
private. To reach it from a phone, explicitly choose the device's LAN/VPN bind
address and `--allow-lan`. Do not change firewalls, expose public HTTP, install a
service, or change global Codex configuration merely to make this work.
HTTP is not encrypted; use a trusted local network or private VPN. This is a
single-user workspace service, not an Internet-facing multi-user application.

`serve --wake-root` or `submit --notify` requests one `codex queue` notification
using OPL's existing executable resolver. The receipt distinguishes attempting,
accepted, failed, and unknown. Acceptance does not prove delivery or integration.
The message carries identifiers and a path, not the reply text. On timeout,
inspect before an explicit `notify --retry`; do not start an agent polling loop.
Without this option, feedback remains durably available to hooks and recovery.
The server is not another chat model and does not impersonate the root.
