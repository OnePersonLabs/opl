---
name: session-reader
description: Safely index, search, inspect, and extract bounded message ranges from large Codex rollout JSONL session logs. Use when Codex needs to find prior user or agent messages, browse recent sessions, search across active or archived session history, inspect rollout metadata, or read a focused transcript without loading raw session files into context.
---

# Session Reader

Use the bundled CLI instead of reading rollout JSONL directly. It streams source files, indexes only canonical user-visible messages, and bounds every body-bearing response.

Resolve the script from this skill directory. On native Windows PowerShell,
run `python -B -X utf8 "<skill-directory>/scripts/session_reader.py"` followed
by the command and options. On POSIX, use `python3 -B -X utf8` with the same
script and arguments. Quote the resolved path and use the active shell's
variable syntax; do not send Bash assignments to PowerShell.

## Workflow

1. Start with `sessions --limit 10` when the target session is unknown.
2. Use `search "terms" --limit 20` to search history newest-first.
3. Use the returned session selector and message numbers with `show SESSION --range START:END`.
4. Use `show SESSION --view all` only when commentary is relevant.
5. Use `inspect SESSION` for counts and schema health without message bodies.

Never `cat`, broadly grep, or load a complete rollout file. Narrow by search results or message ranges. Keep the default output caps unless the task requires a larger bounded value.

## Commands

- `sessions`: List indexed sessions. Filter with `--cwd`, `--since`, `--until`, `--archive`, or `--session`.
- `search QUERY`: Search all canonical messages. Add `--mode literal|regex`, `--roles`, `--phases`, `--context`, or `--order` as needed.
- `show SESSION`: Render user messages and final answers. Add `--view all` for commentary and `--range 12:20` for a logical message range.
- `inspect SESSION`: Show source, message, phase, malformed-line, and freshness statistics.
- `index`: Refresh the incremental cache. Normal read commands refresh automatically; use `--rebuild` only to replace the derived cache.
- `status`: Show cache coverage and staleness without refreshing it.

Use `--format json` for structured single-result output and `--format jsonl` for streaming consumers. Session selectors accept an exact path, full UUID, or unique UUID prefix. Run `--help` on any command for all filters and bounds.

Treat explicit truncation and `next_start` as continuation instructions. Retrieve the next narrow range rather than raising output limits indiscriminately.
