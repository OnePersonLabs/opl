---
name: unslop-log
description: >
  Record a specific agent failure or quality lapse as a timestamped entry in .unslop/log/ -- a
  logbook only, with NO analysis, depth-tracing, or fix. Use when you want the moment captured and
  nothing else: the user calls out a mistake, missed observation, shallow analysis, unnecessary work,
  or ignored instruction, or you catch your own slop mid-flow and don't want to interrupt the work to
  dissect it. Trigger on: "log this", "log that", "that was slop", "you missed X", "/unslop-log".
  For tracing a failure to its root and developing a fix, use /unslop (one live failure, fix
  proven by replay) or /unslop-session-audit (whole session, fix proven by reasoning) instead.
---

# Unslop Log

Fast capture of agent failures. One file per incident, timestamped, in `.unslop/log/`.

This is a logbook -- not an audit, not a fix. `/unslop` and `/unslop-session-audit` do the depth analysis and develop corrective rules. This skill writes a 4-line entry and gets out of the way. Use it when stopping to analyze would derail the work in flight.

## Steps

1. Get the timestamp and create the directory:

   ```bash
   date +"%Y-%m-%d-%H-%M-%S"
   mkdir -p .unslop/log
   ```

2. Write to `.unslop/log/<timestamp>.md` using the Write tool. Four fields, one sentence each:

   ```
   WHAT: <what the agent did wrong>
   SHOULD: <what it should have done instead>
   WHY: <most likely cause -- e.g. task frame lock, shallow read, checklist execution, confidence without verification>
   CONTEXT: <where it happened -- file, command, turn, or conversation phase>
   ```

3. Say "Logged: `.unslop/log/<timestamp>.md`" and stop. No commentary, no apology, no follow-up offer.

## Sourcing the content

If the user provides a description in their message or as arguments, use it directly. If they just say `/unslop-log` with no details, extract the failure from the most recent user correction or complaint in the conversation. If there's nothing obvious, ask what they want to log -- but this should be rare.

Be specific. Name the files, the commands, the artifacts. "Agent made a mistake" is useless. "Agent read both build-desktop-windows.sh and dev-desktop-windows.sh but treated them as independent move targets without noticing 60% shared code" is a log entry you can act on later.

## What this is NOT

- Not a depth ladder (use `/unslop` for that)
- Not a session audit (use `/unslop-session-audit` for that)
- Not a place for fixes or recommendations -- just the observation
- Not something that needs user confirmation before writing
