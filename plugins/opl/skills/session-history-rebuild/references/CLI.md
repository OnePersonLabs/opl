# Rebuild CLI and records

Use `python -B -X utf8` on Windows or `python3 -B -X utf8` on POSIX. Paths below are relative to this skill directory. Keep the frozen cache and outputs outside the skill directory. First run `$opl:session-reader` `index` and `status`; its default cache is `~/.cache/session-reader/index.sqlite3` unless `--cache` was supplied. Copy the indexed SQLite database using SQLite's backup API, not a live filesystem copy. For example:

```python
import sqlite3
with sqlite3.connect("<reader-cache>") as source, sqlite3.connect("<frozen-index>") as target:
    source.backup(target)
```

Choose an explicit UTC cutoff with the same lexical timestamp format as the index. Freeze once for a reconstruction; a newer index requires a new inventory and route review.

```text
python references/rebuild.py --index FROZEN --cutoff UTC --root REPO [--root RELATED] inventory --output candidates.jsonl
python references/rebuild.py --index FROZEN --cutoff UTC --root REPO [--root RELATED] export --routes routes.jsonl --output OUTPUT
python references/rebuild.py --index FROZEN --cutoff UTC --root REPO [--root RELATED] verify --routes routes.jsonl --output OUTPUT
python references/chunk_export.py --conversation OUTPUT/LINEAGE/conversation.jsonl --output PACKETS [--max-bytes 80000] [--dedupe-exact]
python references/merge_replay_events.py --chunks PACKETS --events EVENT_DIR --conversation OUTPUT/LINEAGE/conversation.jsonl --output events.jsonl
```

`--root` defaults to the current working directory. Inventory includes every indexed session through the cutoff because the reader retains only the session's final working directory; an earlier turn could concern another repository. Root and message matches are triage hints (`candidate_reason`), not automatic inclusion. Each candidate includes `session_id`, `cwd`, `source_path`, timestamps, source health counts, and `candidate_reason`. Roots match exact paths and descendants with platform-aware case handling. `--related-term TERM` adds another triage hint. Give unclassified sessions explicit exclusion reasons rather than silently discarding them.

Routes are JSONL with one record for every candidate, no duplicates or extras. Each record has `session_id`, `reason` (nonempty), and `lineages` (object). Each named lineage maps to `"all"`, `null`, or an array of inclusive `[first,last]` message-number ranges. Include every requested lineage on every route, even when excluded (`null`). Optional `spans` is keyed by a known lineage, then a canonical decimal message number string such as `"1"`, then nonoverlapping `[start,end]` character offsets into the canonical message body. Splitting a mixed message is exceptional; document why. The exporter rejects incomplete coverage and invalid spans. `null` and empty selection mean excluded; selected messages after the cutoff are omitted and reported by counts.

Export requires an output path that does not exist and stages complete results before moving them into place. It writes `source-lock.json` with index and route hashes, cutoff, roots, related terms, and candidate count. For each lineage, it writes `manifest.jsonl`, `conversation.jsonl`, and `conversation.txt`. The JSONL is authoritative. A session appears as start, ordered message, end records. Message records include the source path through the manifest, raw line, byte offset, full-body SHA-256, selected text span, and selected text SHA-256. The plain-text renderer writes headers and exact bodies without trimming or deduplication. `verify` recomputes all three files against the frozen index and routes. The route manifest records exclusions and reasons as well as inclusions.

Packets preserve user-turn boundaries. A turn larger than the byte target is emitted alone and marked oversized; inspect it in bounded parts if needed. `--dedupe-exact` replaces repeated long bodies only in packets, with a pointer to the first cited message and hash. The packet manifest records bounds, ordered canonical message references, byte sizes, and SHA-256. Generated packet directories must be empty so stale packet files cannot be mistaken for current output.

Each packet event extract is named after its packet (`0001.jsonl` for `0001.txt`). One event per JSONL row. Required fields: `timestamp`, `session_id`, `message_numbers` (nonempty array of cited message numbers in that packet), `kind` (`user_decision`, `user_request`, `assistant_proposal`, `implementation_report`, `review_finding`, or `unknown`), `statement`, `why`, `evidence_limit`. The merger validates citations, packet hashes and full ordered conversation coverage, then appends `replay_chunk`. It checks evidence shape, not historical truth; review the underlying messages before writing a checkpoint.

Write interpretation artifacts in the target repository's chosen history directory. Start `baseline.md` from code and existing documents as observed at the frozen checkpoint. Then create cumulative, standalone spec, design, and ADR/checkpoint copies only for meaningful changes. Each entry needs message citations, code evidence where applicable, status, and an explicit uncertainty if evidence does not establish the outcome. Append ADR corrections and supersessions rather than rewriting earlier decisions. Keep independent lineages in separate output directories and verify each.
