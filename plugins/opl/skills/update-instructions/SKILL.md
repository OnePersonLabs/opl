---
name: update-instructions
description: Reconcile OPL instruction updates with customized global AGENTS.md, or adopt OPL defaults for the first time. Use when OPL reports an instruction version mismatch or the user asks to merge its latest defaults.
---

# Update OPL Instructions

The user owns their instructions. An OPL version marker records the baseline
last reconciled, not a requirement to match that baseline. Preserve deliberate
additions, edits, and deletions while integrating applicable upstream changes.

## Inspect the effective file

Run `scripts/instructions.py inspect` with Python, relative to this skill's
directory. The helper resolves the active Codex home and effective global file,
including override precedence, and reports `target`, `sha256`,
`bundled_sha256`, and the bundled version.
Use `--home PATH` only for a user-selected home; use `--plugin-root PATH` when
the intended OPL baseline is outside this installed plugin. Read the effective
user file and bundled OPL `AGENTS.md`. Retain the target path, user hash, and
bundled hash from this inspection before drafting. These identify the reviewed
inputs; do not recapture them at application time to bypass a changed input.

- Matching versions: no upstream reconciliation is needed. Explain this unless
  the user also requested a specific customization.
- User version above installed version: report the older installation and stop
  the update; do not downgrade or advance its marker to the lower version.
- Missing file or marker: prepare initial reconciliation without inventing an
  ancestor. Existing instructions are user-owned, not obsolete stock.
- Invalid or duplicate marker: explain that ancestry is uncertain. Prepare an
  explicit reconciliation proposal; resolve the intended baseline with the user
  when needed before relying on a three-way comparison.

Do not install or refresh plugins, change unrelated settings, or write the user
file during inspection. Continue only with the target and baseline identified.

## Recover the previous baseline

For a valid older marker, run:

```text
python scripts/instructions.py baseline --version N --output PATH
```

Use a new, nonexistent temporary output path; the helper refuses to overwrite
an existing file. Pass `--repo PATH` for a verified local checkout
of the OPL repository when available; otherwise the helper retrieves canonical
GitHub history. It searches the history of OPL's `AGENTS.md` for the recorded
instruction version, independently of plugin release versions.

Missing history, no matching version, or different instruction contents with
the same version mean reliable ancestry is unavailable. Surface the helper's
error and propose explicit initial reconciliation instead of guessing which
removals or changes came from the user. Do not pick a convenient historical
snapshot to bypass a collision.

## Prepare and review the merge

Compare previous stock, current user instructions, and installed stock. Build a
complete candidate in a separate temporary file:

- Apply upstream changes where the user left the previous baseline unchanged.
- Carry forward user-only additions, modifications, and deletions. A removed
  routing rule stays removed even if the current defaults still contain it.
- For overlapping behavioral changes, propose a thoughtful combination informed
  by the user's customization. Explain uncertain intent or incompatible outcomes
  with a small before/after example and resolve one topic at a time.
- Preserve the personal `Harness Policies (managed by $opl:configure-harness)`
  section if present. Consider upstream overlaps without regenerating that
  section or duplicating contradictory routing elsewhere.
- For initial reconciliation, distinguish new proposed defaults from existing
  user instructions. Make uncertain removals explicit review decisions.

Place exactly one `<!-- opl-instructions-version: N -->` marker in the candidate,
using the installed baseline's version. A rejected upstream suggestion remains
a customization against that baseline. Preserve unrelated instructions and
their formatting; review applicable instruction conflicts before resolving them.

Show the concrete candidate diff and a concise summary of upstream changes,
preserved customizations, and unresolved choices. Obtain approval of the
reviewed result before applying it. Existing approval of that exact result is
sufficient; a general request to update is not approval of an unseen merge.
Keep questions focused on material decisions and use the host's permitted
question channel. Do not replace the file while a merge decision is unresolved.

## Apply and verify

After approval, run:

```text
python scripts/instructions.py apply --candidate PATH --expected-sha256 HASH --expected-target TARGET --expected-baseline-sha256 BASELINE_HASH
```

Pass the same `--home` and `--plugin-root` overrides used during inspection,
and the three retained review identities as the expected values.
For an originally absent target, use the literal `missing` as the expected hash.
The helper validates the candidate marker, checks for concurrent changes, saves
a byte-exact backup of an existing file, and atomically replaces the effective
file. The marker advances only with that replacement.

If concurrent edits are detected, inspect again and update the candidate and
review for the newly affected content. Do not override the hash check. Surface
backup or replacement failures without claiming a completed update.

Re-run inspection and confirm the effective file matches the approved candidate
and installed version. Report the changes, preserved customizations, and backup
location. Ask the user to start a fresh session to load the resulting global
instructions; do not claim the current session's already-loaded instructions
were replaced.
