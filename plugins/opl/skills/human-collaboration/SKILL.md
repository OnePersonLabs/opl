---
name: human-collaboration
description: Open the shared human inbox for this chat and collaborate through technical reviews, optional questions, and submitted feedback.
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

Use the known root thread ID or `CODEX_THREAD_ID`; never guess it. If an inbox
exists, read `INBOX.md` and use `pending` and `list` before creating more work.
Inspect only the relevant full items with `show H006`.

When the user explicitly invokes `$opl:human-collaboration`, the interactive
root opens the inbox before preparing contributions:

1. Run `init --title <readable-title>` for this root. It creates or reuses the
   project inbox, enrolls the session, and registers the project in the local
   catalog. Preserve reviewed revisions, claims, and outcomes. Do not enroll
   other chats or projects, or transfer another root's work.
2. Run `connect --host lan --allow-lan` to start or reuse the service
   on the host's detected private LAN IPv4 address. Honor a user-requested bind;
   use `connect --host 127.0.0.1` for local-only access. Read
   Delivery and phone access below for network and notification options.
3. After authenticated readiness succeeds, whether `connect` starts or reuses the
   service, open its returned pairing URL in the host browser and report it. This
   URL contains the current GUID and bearer token. Report the host's `lan_ip` and
   render `lan_url` as a clickable Markdown
   link, such as `[Open human inbox](<returned-url>)`. For `local-only`
   access, link `url` and state that a phone cannot reach this listener. Report
   that the service remains running after the turn. On Windows, its terminal
   shows request activity; closing that window stops the server. Keep its bearer token
   private. If connection fails, report the error and evidence
   path; enrollment remains saved. Reconcile a possibly running process before
   retrying startup.

If the explicit request is to pause or restore the server around a local plugin
refresh, follow Local plugin refresh below instead of enrolling or connecting.

Hook-directed recovery starts by inspecting existing work. Recheck
pending input after startup, resumption or compaction, before related commitments,
and before completion. These checks do not enroll a session or start a server.
Do not run `init`, `connect`, or `serve` because a hook requests recovery or during
ordinary chat activity. If the current root is not enrolled, continue independent
work and tell the user to invoke this skill before publishing contributions.
Workers route enrollment requests and contribution proposals to their parent.

Each contribution belongs to one root session. Independent roots can register
in the same workspace; registration does not take another root's work. Workers
propose contributions to their parent; they do not register independent roots.
`pending` with `--thread` returns that root's unresolved responses. A different
root must already be enrolled, inspect ownership, and use
`bind --from-thread <old-root> --reason` for an explicit handoff. Binding does
not enroll the receiving root, reset claims, or replay effects.

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

Use optional `questions` in a published spec when specific answers will help.
Each question has a stable ID, a prompt, and three choices. Put the highest-value
recommendation first. The reader also offers a free-text answer. One brief can
contain several questions after its Markdown context. Keep architecture reviews
and other open invitations free-form when choices would distort the work.

Architecture review invitations are nonblocking. Continue authorized work while
the human is absent. For a nonblocking question, if no independent work remains,
the root can start the first recommended choice as an explicit assumption.
Before acting, use `assume H006 --question <question-id> --reason <reason>`.
State why no independent work remains and why the next step is within scope and
reversible. The question becomes `answer_assumed`; it remains visible and the
human can correct it. Preserve the assumption and recovery point in the existing
task checkpoint. A human correction requires reassessing dependent work.

Do not assume approval, a rule exception, a destructive action, or a decision
whose consequential ambiguity requires input. Use the host's inline
`request_user_input` for legitimate blockers and consequential ambiguity when
the host permits it, at the required time. Otherwise use the required chat
channel. The inbox cannot replace that channel. Do not wait for a review
invitation or manufacture more work after the authorized task is complete.

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

## Local plugin refresh

Use this lifecycle only around an explicit local plugin refresh. From the
workspace being refreshed, run `pause-for-refresh` before the installer and
`resume-after-refresh` after the installer attempt, even if refresh failed.
Both commands use the same local service catalog and workspace. The pause
command checks authenticated readiness, stores whether the service was running
and its bind settings without copying its pairing token, and stops it gracefully
only when it was running. It confirms both that the listener is unavailable and
that the recorded process exited; an unresponsive live process is an error. On
Windows it sends Ctrl+C to the service's own console; on POSIX it sends SIGINT to
the recorded service process. If it cannot confirm the stop, do not refresh.

The resume command starts the service only when the pause record says it was
running. It uses an already-registered workspace from the shared catalog, so the
workspace being refreshed does not need its own human inbox. If the service was
initially down or there is no pause record, it does not start one. A failed
restart leaves the record in place so the same command can retry. A successful
restart returns a new pairing URL; open and report it, because the previous GUID
and pairing link stop working after restart. If the installed helper could not
be updated, the source helper can consume the same record to restore service
availability.

Run the commands with the helper from the current skill directory before the
refresh and from the installed skill directory after it:

```text
<python> -B -X utf8 <skill>/scripts/human.py --workspace <project> pause-for-refresh
<python> -B -X utf8 <skill>/scripts/human.py --workspace <project> resume-after-refresh
```

## Delivery and phone access

The session hooks report outstanding submissions only to their owning root. They
are inactive without a project inbox, do not initialize one, do not invoke a
model, and never block Stop. `PostToolUse` deduplicates notices; startup/resume,
new user turns and Stop re-surface unresolved work. Notifications are not claims.

Enrollment persists. Invoke `$opl:human-collaboration` again to enroll a different
root or restart a stopped service. The service stays running when the agent turn
ends. Add `--wake-root` to `connect` only when queue notifications are requested.
On Windows, `connect` opens a visible terminal owned by the server process.
The terminal shows startup, incoming requests, response status, and shutdown.
It also prints the full pairing URL, including the GUID and bearer token.
Logs omit URL queries, authentication headers, and request bodies. Close the
terminal window or press Ctrl+C to stop the server.
Use `pause-for-refresh` and `resume-after-refresh` only for the lifecycle above;
ordinary recovery does not stop or start the service.
`serve` still runs a foreground service for an individual workspace;
`serve --catalog <runtime-directory>` serves registered workspaces. The default is `127.0.0.1:8766`.
Report the pairing link only after the service responds. It contains a bearer token; keep it
private. `--host lan --allow-lan` selects an active physical Windows adapter,
preferring one with a gateway and then the lowest interface metric. On POSIX it
uses the default route's private IPv4 address. Discovery failure is an explicit
error; choose a literal bind address instead. Phone reachability depends on the
network and firewall; successful host readiness does not prove it. For a
specific LAN/VPN address, use that literal IP and `--allow-lan`. Do not change firewalls, expose public HTTP, install a
service, or change global Codex configuration merely to make this work.
HTTP is not encrypted; use a trusted local network or private VPN. This is a
single-user local service, not an Internet-facing multi-user application.

Each server start creates a new GUID, a random identifier in the pairing URL's
`guid` query parameter. Every request must include that GUID, including page,
asset, and API requests. Without the current GUID, the server sends no response
and holds the connection until the client disconnects or the server stops.
The browser and readiness helper carry it automatically. API requests also
require the bearer token. After a restart, open the new pairing link; an old
link cannot load the page. A held connection uses a request thread and socket
until it closes. Keep this service on the authorized trusted network.

The browser starts with a newest-first combined message feed. It can filter to
one session. Lists show available projects and sessions that have contributions,
including completed ones. Unavailable projects and empty sessions are omitted;
their stored history is retained. The session list puts sessions needing human input first, then
sessions awaiting agent outcomes, then sessions with neither. Counts distinguish
`need you`, `with agent`, assumed answers, and deferred work. The browser refreshes every three
seconds while visible and when it regains focus. Background refresh preserves
the open composer. These HTTP reads do not notify or invoke agents.
Human-initiated contributions must select a recipient when several sessions are
registered. Item requests include the workspace ID so identical H-numbers in
different projects cannot route a response to the wrong project.

`connect --wake-root`, `serve --wake-root`, or `submit --notify` requests one `codex queue` notification
using OPL's existing executable resolver. The receipt distinguishes attempting,
accepted, failed, and unknown. Acceptance does not prove delivery or integration.
The message carries identifiers and a path, not the reply text. On timeout,
inspect before an explicit `notify --retry`; do not start an agent polling loop.
Without this option, feedback remains durably available to hooks and recovery.
The server is not another chat model and does not impersonate the root.
