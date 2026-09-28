# Setup and daily operation

Use `scripts/slop.py setup` to inspect and reconcile configuration and scheduling; `--dry-run` reports proposed changes. Do not wipe existing data. Keep one schedule owner per repository.

Configuration is `$CODEX_HOME/slop-buster.toml`, falling back to `~/.codex/slop-buster.toml`. `SLOP_BUSTER_CONFIG` or `--config` selects an isolated configuration. It identifies the repository, source homes, deadline, schedule, and explicit model/effort routes.

For this installation, use `C:\dev\projects\slop-intelligence`. Include native Windows and the user's default WSL Codex homes when available; Docker's distribution is not a user source. Deduplicate aliases of the same session.

Schedule 09:00 America/Chicago in the logged-on user's interactive Windows session. WSL setup manages the same owner task through Windows interoperability. Catch up missed runs when an interactive session becomes available. A logged-out session cannot display the requested console.

The daily launcher starts one Codex root at gpt-6-sol/medium and invokes this skill. Readers use gpt-5.6-luna/medium; justified abstract synthesis uses gpt-6-sol/high. Verify actual delegation in a finite synthetic smoke before corpus processing. Do not silently substitute models.

The skill resumes or prepares work and delegates it; it must not recursively invoke the launcher. No-new-work runs finish without model analysis. The 30-minute deadline checkpoints incomplete work without skipping the backlog.

Release the processing lock before the results console waits for the user to close it. Report duration, scope, reviewed and pending counts, failures, catalog changes, and available usage. Durable receipts preserve results after the console closes.
