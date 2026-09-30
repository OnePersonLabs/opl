---
name: probe-agent-profile-usage
description: Run a bounded live Codex subagent-profile activation probe, capture what selected agents actually received, and restore temporary profile edits. Explicitly invoke only for profile-usage testing.
---

# Probe Agent Profile Usage

Use this skill only when explicitly asked to test Codex subagent profile discovery, selection, or context receipt. It edits discovered profile TOMLs temporarily and launches one bounded `codex exec`.

Run `scripts/profile_probe.py discover --repo REPO` first. It reads the active user Codex home (`CODEX_HOME`, otherwise `~/.codex`) and the repo's `.codex/config.toml`, follows each `agents.<name>.config_file` relative to its declaring config, and adds direct `*.toml` files from both `agents/` directories. It deduplicates identical paths and stops on distinct files with the same profile name because receipts could not distinguish them. This is an inventory of candidate profiles; Codex still decides which profiles it loads for the actual trusted project.

Choose one realistic, bounded task that gives the expected profiles a natural reason to contribute. Do not name profiles or tell the root to spawn subagents. Keep the expected list to profiles whose stated responsibilities fit the task; record missing expected receipts as a failed selection. Do not retry unless the user explicitly requests a bounded escalation sequence.

Put the task prompt in a UTF-8 text file and run:

```powershell
python plugins/opl/skills/probe-agent-profile-usage/scripts/profile_probe.py run `
  --repo . `
  --prompt-file C:/path/to/probe-prompt.txt `
  --log C:/path/to/profile-usage.jsonl `
  --expected opl-docs-researcher `
  --expected opl-explorer `
  --timeout 600
```

Omit `--expected` to expect every discovered profile. The runner instruments all discovered profiles, including directory-only profiles and config-file references, deduplicates shared files, and sets profile model, effort, and sandbox to `gpt-6-luna`, `low`, and `workspace-write`. Select root model and effort with `--model` and `--effort`; defaults are `gpt-6-luna` and `medium`. Each profile is instructed to append its observed runtime and context receipt plus its verbatim parent task assignment to JSONL before doing task work. The runner checks only lines appended during the current run and stops the Codex process tree as soon as every expected profile has logged, or reports a timeout, early exit, or missing profiles.

For `run`, omit `--home`: discovery uses the inherited `CODEX_HOME` or `~/.codex`, matching the child `codex exec` process. The runner rejects a custom home argument rather than instrumenting one home and launching with another.

The runner restores every profile byte-for-byte on success or failure by default. Use `--keep-instrumented` when the user asks to leave the profile changes in place. Keep the JSONL and per-model/effort `.exec.txt`, `.stdout`, and `.stderr` artifacts to inspect the outcome. If an earlier manual `instrument` was interrupted, restore it with:

```powershell
python plugins/opl/skills/probe-agent-profile-usage/scripts/profile_probe.py uninstrument --repo . --log C:/path/to/profile-usage.jsonl
```

`instrument` and `uninstrument` can also be run separately. Instrumentation is idempotent for an unchanged file set. If a profile changes while instrumented, restoration refuses to overwrite it; inspect the reported path and restore deliberately. Do not use temporary homes/configs for the live probe. Temporary fixtures are appropriate only for isolated unit checks.

Report discovered sources, expected profiles and why they fit, actual JSONL receipts, process stop reason, restoration result, and any gaps. Runtime model/effort and inherited context must come from the receipts, not TOML settings.
