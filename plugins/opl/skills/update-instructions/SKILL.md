---
name: update-instructions
description: Update an outdated global AGENTS.md from installed OPL defaults after one approval, saving the existing file as a dated backup.
---

# Update OPL Instructions

The user owns their global instructions. When an update is available, inspect
the effective target and installed OPL version, then ask once whether to replace
the target with the installed `AGENTS.md`. Explain that active custom rules will
be replaced and the existing file will be saved as a dated backup. A clear yes
authorizes that update; do not ask the user to review a candidate or diff.

## Inspect and ask once

Run `scripts/instructions.py inspect` with Python, relative to this skill's
directory. The helper resolves the active Codex home and effective global file,
including override precedence, and reports `target`, `sha256`,
`bundled_sha256`, and the user and bundled versions. Use `--home PATH` only when
the user selected a home; use `--plugin-root PATH` when the intended OPL
instructions are outside this installed plugin.

- Matching versions: report that the target is current and stop.
- User version above installed version: report that this installation is older
  and stop. Never downgrade the target.
- Missing, unversioned, or invalid target: include that state in the one update
  question. If the user agrees, replace it with installed OPL instructions and
  preserve any existing bytes in a backup.
- Older valid version: state both versions and ask once whether to update.

Before asking, explain that replacing the target discards active custom rules.
The user can recover them from the exact backup, but they are not merged into
the new file. If the user declines, stop without writing files.

## Apply after approval

On approval, run the helper's `apply` command. It reads the installed OPL
`AGENTS.md` directly:

```text
python scripts/instructions.py apply --expected-sha256 HASH --expected-target TARGET --expected-bundled-sha256 BUNDLED_HASH
```

Use the `target`, `sha256`, and `bundled_sha256` returned by the initial
inspection. For a missing target, pass `missing` as its expected hash. Pass the
same `--home` and `--plugin-root` overrides used during inspection.

The helper refuses to downgrade a newer target, verifies that the target and
installed instructions have not changed since inspection, saves a byte-exact
backup, and atomically replaces the target. Backup names use
`AGENTS.md.opl-backup-YYYYMMDD-NNN`; `NNN` starts at `001` each day and increases
to avoid overwriting an earlier backup. A failed backup or replacement is an
error; never report success unless the replacement completed.

Re-run inspection and confirm the effective target has the installed version
and hash. Report the backup location. Ask the user to start a fresh session to
load the resulting global instructions; do not claim the current session's
already-loaded instructions were replaced.
