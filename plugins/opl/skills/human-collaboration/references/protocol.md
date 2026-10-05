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
cross-clone collaboration service. Use one service against one workspace on a
local filesystem. Back up the entire `.human` directory while the server and
writers are stopped, including SQLite journal files if present. Retain relevant
accepted decisions in the project's normal versioned documents. Never include
credentials in briefs or source snapshots.

## Example workflow

Resolve the installed skill path first. These shell examples run from that
skill's `scripts` directory; `--workspace` is an existing project directory and
`--thread` is the actual root ID. They do not create a project for you.

```sh
python3 -B human.py --workspace /work/project --thread root-thread-id init
python3 -B human.py --workspace /work/project --thread root-thread-id publish review.json
python3 -B human.py --workspace /work/project serve
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
ownership. Agent publication and disposition still require the bound root.

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
Preparation is separate from queue position. Only the bound root can mark an
unprepared candidate ready. Deferral or reopening does not prepare a brief;
a new candidate revision requires preparation again.
Idempotent retries return the same receipt and reject changed payloads under the
same ID. Claims and outcomes are serialized in SQLite; code changes outside the
database must be reconciled through the owning agent's checkpoint after a crash.

The UI refreshes on demand, not through model-mediated polling. It provides a
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
