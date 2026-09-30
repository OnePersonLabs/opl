---
name: session-history-rebuild
description: Reconstruct a repository's development history from canonical Codex sessions when a complete, auditable conversation and evolving design record are explicitly requested.
---

# Session History Rebuild

Use this skill only on explicit invocation. When loaded, announce it by name: `Using $session-history-rebuild.` The default scope is the current repository's indexed session rollouts. Add related checkout roots or separate lineages only when evidence calls for them; never infer a lineage from a similar name alone.

Use `$opl:session-reader` as the canonical index provider. Refresh its index, confirm its `status` has no relevant stale sources, then freeze a SQLite snapshot and UTC cutoff. Never read raw rollout JSONL directly. The helpers in [references/CLI.md](references/CLI.md) read only the frozen index.

Inventory every indexed session before routing; root and text matches are triage hints, since the index records only a session's final working directory. Inspect unclassified, ambiguous, or referenced sessions with bounded `$opl:session-reader` searches and ranges. Give every candidate an explicit disposition and reason for each lineage, including exclusions. A working directory alone does not establish ownership of every message. Check mixed sessions at message level; use ranges or source spans when needed.

Export the full canonical user and assistant sequence, grouped by session, to `conversation.jsonl` and `conversation.txt`. Preserve exact message bodies and source hashes. Dedupe only optional interpretation packets, never the canonical conversation. Verify the export against the frozen index, routing file, and deterministic text renderer.

Replay bounded packets in order, recording user decisions, assistant proposals, implementation reports, review findings, and unknowns with message citations and evidence limits. For large histories, use fresh bounded subagents with one packet and one owned event file each; merge their extracts and integrate the history sequentially. Keep roles and models configurable under the current environment's delegation rules. Merge and validate event extracts before writing history prose. Establish a code-first baseline from repository evidence, then maintain cumulative standalone checkpoints for significant spec, design, and ADR changes. Append corrections and supersessions to ADR history instead of silently rewriting earlier decisions. Distinguish requested, proposed, implemented, reviewed, superseded, rejected, and unknown states. Do not promote an assistant claim to a user decision or mix independent lineages. Cite source messages and code at each meaningful checkpoint.

Read [references/CLI.md](references/CLI.md) for commands, route and event schemas, verification, and packet handling. The scripts there are executable and reusable for any repository; they do not contain project-specific routes or conclusions.
