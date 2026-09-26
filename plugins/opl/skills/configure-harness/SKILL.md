---
name: configure-harness
description: Configure a Codex harness by inventorying available skills, plugins, tools, and routing; comparing evidence and cost; interviewing the user by capability; and testing proposed changes before applying them. Use for a personal harness setup or a measured harness reconfiguration, not for a one-off task.
---

# Configure Harness

Build a usable, user-owned harness from the capabilities actually available in the selected Codex home. Treat a skill, plugin, tool, and instruction rule as different objects. Availability, eligibility, activation, and task success each need their own evidence. Keep choices and test results under `<selected Codex home>/opl/harness/` so an interrupted run can resume.

Target one curated default setup. Introduce separate task profiles only when
evidence shows a conflict that conditional guidance cannot resolve cleanly.

## Establish scope and inventory

Resolve the selected Codex home and working directory from the request. For a first setup, inspect the effective global instructions, repository instructions, enabled and disabled installed plugins, installed and cached skill packages, configured MCP tools, callable CLIs, and discoverable catalog entries. Run `python scripts/harness.py init --home PATH`, then `discover --home PATH --cwd PATH`; pass `--marketplace PATH` for each known marketplace and `--cli NAME` for each relevant CLI probe. The script is relative to this skill. Complete paginated skill and plugin listings. Read the inventory and confirm the effective state before advising a change. A catalog listing does not prove that a tool is installed, enabled, authenticated, callable, or free to use.

Use the inventory as one source of truth, including the enabled/disabled distinction and provenance. Check current primary sources for material claims about capability, supported configuration, eligibility, price, recurring free access, time-limited trials, self-hosting, and limits. Record the source and observation date. For the default free baseline, exclude paid-only and trial-only operating modes and routes with required paid dependencies; recurring free quotas and suitable self-hosted modes remain eligible. Do not label a trial, promotional credit, or self-hosted software as a recurring free hosted service. Mark an unverified claim unknown. Read [references/workflow.md](references/workflow.md) when comparing candidates, interviewing the user, or preparing changes.

## Choose capability by capability

Group real user needs into small capability categories. For each category, show a short card for each viable option: exact name, what it enables, current availability, material cost or eligibility, and evidence quality. The inventory's description summary is at most 256 characters per item; keep the exact name in its own field and do not treat the summary as the full instruction text. Ask about one category at a time and write the choice and reason through `decide --home PATH --decision PATH`. Reuse recorded choices when resuming; revisit one only when the user changes it or new evidence makes it stale.

Compare the current route and the strongest alternative before adding a capability. Prefer disabling a redundant route before adding another overlapping instruction. Choose the narrowest supported scope: per-skill invocation policy when that owns activation; plugin enablement when the whole plugin is at issue; task-specific instructions where no supported control exists. Never patch installed caches as configuration. An inventory or recommendation alone does not authorize installation, external account creation, payment, or changes to the user's live profile.

## Measure uncertain behavior

For activation, selection, or recovery behavior that materially affects the choice, read [references/evaluation.md](references/evaluation.md). Agree on a finite run budget and record it with `plan --home PATH --spec PATH` before sampling. Use a fresh native Luna agent to execute the explicit capability tests in one bounded batch and a separate fresh Sol agent to judge only the resulting evidence against the predefined rubric. Do not send either agent the whole conversation or the desired result. Record observations with `record --home PATH --run ID --record PATH` and conclusions with `report --home PATH --run ID --report PATH`.

Use fresh context for each unaided production-route test. Repeat only when the choice depends on consistency, within the agreed budget; at most one bounded follow-up batch is the default. Reuse the bounded Luna and Sol agents for that follow-up; fresh unaided production-route contexts remain separate. Report supported, rejected, conditional, or inconclusive conclusions without promising that future routing is guaranteed. If a required model is unavailable, stop that test and disclose the gap; do not silently substitute a model.

## Review, apply, and recover

Show the concrete proposed state, ownership of each change, evidence, remaining uncertainty, and expected effects. Use `prepare --home PATH --files PATH --output PATH` with a JSON list of reviewed `target` and `candidate` files to prepare file changes. Use `apply --home PATH --plan PATH` only after the reviewed change is authorized. Retain the returned receipt before proceeding to another change; use `rollback --home PATH --receipt PATH` for a failed or rejected application. The managed section may be absent on first setup: review its placement, then create exactly one. Stop on duplicate headings or ambiguous ownership rather than guessing where text belongs.

For OPL startup configuration, present the discovered OPL roles and each
required setting from the plugin-root `config.defaults.toml` file before
preparing a transaction. Reconcile only OPL-prefixed role registrations and
that documented startup baseline. Preserve non-OPL registrations and unrelated
configuration.

For a global instruction change outside the harness-owned `Harness Policies (managed by $opl:configure-harness)` section, reconcile the whole user-owned file through `$opl:update-instructions`; do not overwrite personal edits. Put essential, unmeasured constraints inline. Add compact conditional pointers to category policies and procedures only when their targets resolve and their route can be verified; avoid circular pointers. Add a runtime recovery hook only after measured failures show a hook is needed; no hook is part of the default setup. Verify the root route, a relevant documentation event, and subagent behavior separately in fresh contexts. Give the user the durable run location and any remaining uncertainty.
