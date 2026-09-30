# Setup and daily operation

Use `scripts/slop.py setup` to create the local configuration and initialize the evidence repository; `--dry-run` reports proposed changes. Do not wipe existing data.

Configuration is `$CODEX_HOME/slop-buster.toml`, falling back to `~/.codex/slop-buster.toml`. `SLOP_BUSTER_CONFIG` or `--config` selects an isolated configuration. It identifies the repository, source homes, deadline, and explicit model/effort routes.

For this installation, use `C:\dev\projects\slop-intelligence`. Include native Windows and the user's default WSL Codex homes when available; Docker's distribution is not a user source. Deduplicate aliases of the same session.

The manual daily launcher starts one Codex root at gpt-6-sol/medium and invokes this skill. Readers use gpt-5.6-luna/medium; justified abstract synthesis uses gpt-6-sol/high. Verify actual delegation in a finite synthetic smoke before corpus processing. Do not silently substitute models.

Run `scripts/slop.py daily` manually when you want a bounded audit. The launcher resumes or prepares work and delegates it; it must not recursively invoke itself. No-new-work runs finish without model analysis. The 30-minute deadline checkpoints incomplete work without skipping the backlog.

Release the processing lock before the results console waits for the user to close it. Report duration, scope, reviewed and pending counts, failures, catalog changes, and available usage. Durable receipts preserve results after the console closes.
