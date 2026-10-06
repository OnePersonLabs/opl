# Human inbox protocol

## Files and authority

```text
project/.human/
  state.sqlite3                Transactional state, drafts and immutable receipts
  INBOX.md                     Generated priority view
  DECISIONS.md                 Generated consequential-decision view
  items/H006/brief-v1.md        Published brief and human-owned # Reply
  items/H006/submissions/*.md   Readable submitted responses
  items/H006/outcomes/*.md      Readable root dispositions and evidence
```

The database is authoritative for coordination and submitted content. Markdown
indexes and receipts are reconstructible views. Published brief files are not:
they can contain unsent human edits, so the helper never replaces them. A missing
previously published brief is an explicit error requiring restoration from a
backup. A version committed before its initial file write can be recovered by
`refresh`. No helper automatically edits project code or commits `.human/`.

`.human/.gitignore` excludes local workflow state. This design persists across
processes and compaction on the same workstation; it is not cloud sync or a
cross-clone collaboration service. A combined service reads registered workspace
stores on the local filesystem. Back up each entire `.human` directory while the server and
writers are stopped, including SQLite journal files if present. Retain relevant
accepted decisions in the project's normal versioned documents. Never include
credentials in briefs or source snapshots.

## Example workflow

Enrollment and service startup require an explicit `$opl:human-collaboration`
invocation. Resolve the installed skill path first. These shell examples run from that
skill's `scripts` directory; `--workspace` is an existing project directory and
`--thread` is the actual root ID. They do not create a project for you.

```sh
python3 -B human.py --workspace /work/project --thread root-thread-id init --title "Project review"
python3 -B human.py --workspace /work/project connect --host lan --allow-lan
python3 -B human.py --workspace /work/project --thread root-thread-id publish review.json
```

`review.json` is a complete example of the input shape. In real work replace its
illustrative reasoning with inspected project context and add relevant sources.

```json
{
  "title": "Separate retained evidence from bounded model context",
  "summary": "Review whether session storage and inference views should have separate lifetimes.",
  "why_now": "The callers have not yet adopted the storage contract.",
  "kind": "architecture review",
  "priority": 10,
  "decision": true,
  "blocking": false,
  "state": "ready",
  "sources": [],
  "brief": "# The decision\n\nThis is an illustrative design question, not a claim about current code.\n\n## Proposed flow\n\n```text\nRetained events -> task-specific view -> predictor\n```\n\n## Concrete case\n\nA reconnect requires older ensemble context but the predictor can accept only a bounded input.\n\n## Alternative\n\nDiscard older events when trimming inference context. This simplifies storage but prevents later reinterpretation.\n\n## Tradeoff and reversal test\n\nSeparate lifetimes preserve evidence at a storage cost. Reverse this recommendation if a measured retention constraint dominates the value of older evidence.\n\n## Your contribution\n\nChallenge the ownership boundary or demonstrate a case it mishandles. Independent playback work can continue."
}
```

After editing the created brief under `# Reply`:

```sh
python3 -B human.py --workspace /work/project submit H001
python3 -B human.py --workspace /work/project --thread root-thread-id pending
python3 -B human.py --workspace /work/project --thread root-thread-id claim submission-id
python3 -B human.py --workspace /work/project --thread root-thread-id outcome submission-id outcome.json
```

`submission-id` must be the actual ID returned by `submit`, not an H-number.
`outcome.json` has this shape; its claims must describe work actually completed:

```json
{
  "disposition": "explained",
  "text": "The storage contract and inference budget are separate responsibilities. Which reconnect case would invalidate this boundary?",
  "source_review": "No source snapshot was attached to this illustrative question; no implementation was verified.",
  "references": []
}
```

Dispositions: `adopted`, `partial`, `not_adopted`, `explained`, `follow_up`.
The last two return the item to the human. Design agreement does not establish
implementation correctness. A newer unresolved submission is never cleared by
an outcome for an earlier response.

`contribute note.json` accepts `title`, `body`, and a stable `request_id`. Reuse
that ID for an exact retry; use a new ID for a genuinely new contribution. It
creates the item and its first submission atomically without requiring root
ownership. In a workspace with several sessions, supply the recipient root with
`--thread` before `contribute`. Agent publication and disposition require the item's owning root.

## Sessions and combined service

The explicit `$opl:human-collaboration` workflow uses `init` to register an
independent root; it does not transfer existing contributions. Ordinary chat
hooks and collaboration recovery do not enroll roots or start the service.
The workspace database stores session titles and an owner for each item.
Opening a schema-1 or schema-2 inbox migrates its coordination records transactionally:
existing items retain the previous root as owner. Briefs, drafts, submissions,
claims, reviewed revisions, and outcomes remain intact. Use the updated helper
after migration; older helpers cannot read schema 3.

`bind --from-thread <old-root> --reason <reason>` transfers only that session's
items to the already-enrolled root supplied by `--thread`. Enroll a new receiving
root through `$opl:human-collaboration` first; `bind` does not enroll it. If several
roots exist, the source must be explicit. Inspect partially applied work before handoff. Claims and
outcomes remain evidence of prior work, not instructions to replay it.

`connect` records the workspace in a private local catalog and starts or reuses
one background service. On Windows its runtime files are under
`%LOCALAPPDATA%/OPL/human-inbox`; `OPL_HUMAN_RUNTIME` selects an isolated runtime
for deterministic tests. The catalog stores workspace locations and connection
information; project SQLite stores remain authoritative for contributions.
The service does not change global Codex settings, install a system service,
or configure a firewall. Invoke `$opl:human-collaboration` again to restart a stopped
service with `connect`; recovery checks do not restart it.
The explicit skill uses `connect --host lan --allow-lan` for a phone link.
Startup receipts report `lan_ip`, `lan_url`, and `access`; render the returned
URL as a clickable Markdown link after readiness. A loopback-only receipt has
`access: "local-only"` and no LAN URL. Use `--host 127.0.0.1` for this mode.
Automatic LAN selection requires a private IPv4 address and fails explicitly
when none is available. An explicit LAN/VPN IP remains supported. The service
binds only the selected address; it does not change firewall or router settings.
The foreground `serve` command remains available;
`serve --catalog <runtime-directory>` combines registered workspaces.

Unavailable registrations remain in the catalog and API diagnostics. Healthy
workspaces remain accessible independently. The browser lists only available
projects and sessions with contributions; completed contributions remain
visible. It omits unavailable projects and empty sessions without deleting
their history or assuming that unavailable projects have no pending work.

The combined API identifies a session with its workspace UUID and root ID.
Every item route includes a workspace UUID; it never accepts an arbitrary
filesystem path from the browser. Human-initiated contributions select a
session explicitly when more than one is available.

The initial All messages view shows brief publications, human submissions,
and agent outcomes from newest to oldest. Draft saves do not create messages.
A session filter applies to the feed and queue views. Session counts show
ready/active items as `need you`, unresolved responses as `with agent`, and
candidate/deferred items as `later`. Sessions needing the human sort first by
question priority, recent activity, and stable ID. Sessions waiting on agents
follow; sessions with no pending work appear last. Within those groups, recent
activity sorts first, followed by stable ID.

## Optional questions and assumptions

A published spec can include a `questions` array after its free Markdown brief:

```json
{
  "questions": [
    {
      "id": "approach",
      "prompt": "Which approach should the agent start?",
      "options": ["Use the existing module", "Split the module", "Run an experiment"]
    },
    {
      "id": "first-case",
      "prompt": "Which case should be checked first?",
      "options": ["The common case", "A recovery case", "A boundary case"]
    }
  ]
}
```

This fragment extends the complete publication spec above. Each question has
exactly three choices, with the recommendation first. The fourth browser choice
accepts free text. Stable question IDs are unique within the reviewed revision.
Briefs without questions retain the free-form reply composer.

Structured drafts use the same compare-and-swap version as the Markdown reply.
Send can include a reply, selected answers, or both. A selection uses
`{"option": 0}`, `{"option": 1}`, or `{"option": 2}`; free text uses
`{"text": "Your answer"}`. The `answers` object maps question IDs to these
values. Unanswered questions remain open. Submissions retain the exact answers
and reviewed definitions, so later wording changes do not reinterpret feedback.

The owning root can use `assume H001 --question approach --reason <reason>` for
a prepared, nonblocking question on the current revision. This records the
first recommendation in state `answer_assumed`, its reason, and a message in
the chronological feed. It does not create a human submission or claim human
agreement. If all questions are assumed and no reply awaits disposition, the
contribution has state `answer_assumed`; its session shows the assumed count.
An explicit agent follow-up remains Needs you even if other questions have
assumed answers. A human response returns it to With agent; later retries do
not erase a newer follow-up.
The human can send a different answer, which returns the contribution to
With agent for reconciliation. Other open questions remain actionable.

The root may assume only when independent authorized work is exhausted and
the proposed action is within scope and reversible. Architecture review
invitations never pause work. Real blockers, required permissions, rule
exceptions, and consequential ambiguity use the host's inline input channel.
Record assumptions and recovery points in the existing task checkpoint.

## HTTP and concurrency

The phone service exposes only inbox/item reads, captured source reads, draft
saves, explicit submission, human-initiated contribution, and human queue actions.
It does not expose arbitrary filesystem reads, shell execution, root binding,
publication, claims, or outcomes. Sources are explicitly captured, workspace-
relative files, at most 12 per brief and 512 KiB per file. Reply and brief text is
bounded at 128 KiB. Raw HTML is displayed as text. SVG diagrams are image content,
not executable DOM. Source links distinguish reviewed snapshots from current files.

All API requests require the pairing bearer token. Host and Origin checks reject
cross-origin requests; no CORS or cookie authorization is provided. Non-loopback
binding requires `--allow-lan`. The bind must be a literal IP; localhost names are
accepted by the HTTP host check. Pairing tokens are session-scoped and change on
server restart. Phone drafts use localStorage keyed by workspace ID, item and
revision; the token uses sessionStorage. Reopen a new pairing link after restart.

Phone draft writes use compare-and-swap version numbers. A conflicting device
must choose which draft to retain. Unsent Markdown and web drafts stay separate.
Submitted content is immutable, identified by request ID and reviewed revision.
The reader's Brief revision selector reopens older briefs and their drafts.
The queue and revision checks account for drafts on every published revision.
Preparation is separate from queue position. Only the owning root can mark an
unprepared candidate ready. Deferral or reopening does not prepare a brief;
a new candidate revision requires preparation again.
Idempotent retries return the same receipt and reject changed payloads under the
same ID. Claims and outcomes are serialized in SQLite; code changes outside the
database must be reconciled through the owning agent's checkpoint after a crash.

The browser reads updated snapshots every three seconds while visible and on
focus or visibility return. Automatic updates change the feed, session list,
and open read-only question status and conversation without replacing the
composer. Manual Refresh also reloads the open brief.
HTTP reads never queue agent messages. The UI provides a
small safe Markdown reader: headings, paragraphs, lists, quotes, fenced code,
bold, inline code, HTTP(S) links, and captured SVG/PNG/JPEG diagrams. It is not a
full Markdown editor, Mermaid interpreter, repository explorer, or a hosted LLM.

## Development checks

```sh
python3 -B tests/unit/opl/test_human_collaboration.py
python3 -B tests/ui/opl/test_human_collaboration_ui.py
npm run test:contract -- --plugin opl
npm run test:unit -- --plugin opl
npm run test:ui -- --plugin opl
npm run test:installed -- --plugin opl
```

Run from the repository root. The runtime requires only Python's standard
library. Browser tests require a development-only Playwright Python installation
and Chromium; set `OPL_CHROMIUM_BIN` when it is not on PATH. They fail explicitly
when those prerequisites or browser access are unavailable; they do not install
packages or waive the gate. Set `OPL_UI_EVIDENCE` to write screenshots outside the
repository. No tests invoke a model. Live queue delivery, hook trust, and installed
Codex behavior require a separate installed-host check.
