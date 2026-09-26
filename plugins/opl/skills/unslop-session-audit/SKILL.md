---
name: unslop-session-audit
description: "Whole-session behavioral audit that traces AI agent failures to their systemic origins -- instruction vulnerabilities, training priors, architectural mistakes -- using iterative depth climbing and cross-domain root cause analysis, and proves each fix by REASONING (no replay). Use when the user says '/unslop-session-audit', 'audit this session', 'what went wrong', 'find all the slop', 'session postmortem', 'what could be better', or wants to analyze any session's quality. Also use when they want ALL slop in a session found at once rather than one at a time, or the session is old/unreachable so replay isn't practical."
---

# Unslop Audit -- Whole-Session Behavioral Audit

Not a slop logger. Not a linter for agent behavior. This is a cognitive tool that reverse-engineers agent failures to their systemic origins and produces fixes at the correct depth -- the depth where the fix is a cure, not a patch.

The methodology is built on one question the agent almost never asks: **"Why does the thing I'm fixing exist?"** That question breaks the agent out of execution mode ("is my fix correct?") and into premise-questioning mode ("should this fix exist at all, or is the real problem upstream?"). Every technique in this skill is in service of asking that question iteratively, adversarially, and across domains until the answer stops revealing deeper structure.

This skill validates fixes by **reasoning** -- adversarial self-probing and the patch-vs-cure test. It does not run the fix. Its sibling `/unslop` does the opposite: one failure, fix proven empirically by replaying the session under candidate rules. Reach for replay when you have a single live failure and want proof the rule actually changes behavior; reach for this when you want every failure in a session surfaced and reasoned to root.

## When to Use

- **`/unslop`**: One specific mistake, current live session, fix **proven by replay**. Single-instance, empirical.
- **`/unslop-session-audit`** (this skill): A whole session -- current or past. Batch analysis, grouped findings, systemic fixes **proven by reasoning**. No replay.
- **`/unslop-log`**: Just record the incident, no analysis at all.

## Target Session Routing

This `.agents` skill can be used by any worker that supports the standard skill layout. Route by the **session being audited**, not by the worker running the skill:

- Claude Code sessions: `~/.claude/projects/<project-hash>/<session-uuid>.jsonl`; records look like top-level `user`/`assistant` messages with `sessionId` and `uuid`.
- Codex sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl`; records look like `session_meta`, `turn_context`, `event_msg`, and `response_item`.
- If the path or format is ambiguous, run the extractor with `--agent claude` or `--agent codex`. Otherwise leave `--agent auto`.

## Context Window Protection

Session files can be 10K+ lines. The methodology keeps the main agent's context clean:

1. **Scripts extract and filter** -- Python parses the JSONL, produces a trimmed file
2. **Sub-agents do the heavy reading** -- they consume the trimmed file and produce structured findings
3. **Main agent synthesizes** -- receives structured results, not raw session data

Never load a raw session JSONL into the main context window.

---

## Step 1: Locate the Session

Session JSONL files live in different roots by target agent:

- Claude Code: `~/.claude/projects/<project-hash>/<session-uuid>.jsonl`
- Codex: `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl`

If the user specifies a session (by UUID, path, or description like "yesterday's session"), find it. Otherwise, list recent sessions using the current shell.

In PowerShell:

```powershell
$sessionRoots = @("$HOME/.codex/sessions", "$HOME/.claude/projects") | Where-Object { Test-Path -LiteralPath $_ }
Get-ChildItem -LiteralPath $sessionRoots -Recurse -File -Filter '*.jsonl' | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName, LastWriteTime
```

In a POSIX shell:

```bash
find ~/.codex/sessions ~/.claude/projects -type f -name '*.jsonl' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -20
```

## Step 2: Extract Session Content

Run the shipped extraction script directly -- it writes a trimmed transcript to
the system temporary directory without consuming context (only Step 3's
sub-agent reads the output). Resolve the script from the directory containing
this loaded `SKILL.md`.

In PowerShell:

```powershell
$auditSkillDir = '<absolute directory containing this SKILL.md>'
python -X utf8 "$auditSkillDir/scripts/extract-session.py" '<session.jsonl>' --agent auto
```

In a POSIX shell:

```bash
AUDIT_SKILL_DIR="<absolute directory containing this SKILL.md>"
python3 -X utf8 "${AUDIT_SKILL_DIR}/scripts/extract-session.py" "<session.jsonl>" --agent auto
```

It detects Claude vs Codex logs unless overridden with `--agent claude` or `--agent codex`. It filters to behavioral turns, keeps text + tool calls (name + 200 chars of input) + tool results (200 chars), numbers each turn, and writes `unslop-session-<uuid>.txt` in Python's system temporary directory. Use the absolute `out` path returned in its JSON response. Long fields are reduced to first/last 100 chars so structure survives without bulk. A soft 50KB cap drops the **oldest** turns first (redirects and fixes cluster in the tail) and records a `NOTICE` line with the count -- never a silent truncation. Override with `--max-kb <N>` or `--out <path>`.

The output looks like:

```
=== TURN 1 [user] ===
<content>

=== TURN 2 [assistant] ===
<text content>
[TOOL: Edit] input: {"file_path": "/home/user/...
[TOOL_RESULT] The file was updated...
```

## Step 3: The Analysis

This is the core of the skill. Dispatch to a sub-agent (opus for depth, sonnet for speed) with the extracted session file AND the relevant instruction stack files (AGENTS.md, rules, skill instructions, hooks). The sub-agent executes the full methodology below.

### Phase A: Premise Scan

Do NOT scan for a checklist of known slop categories. Instead, read the session and notice where the agent acted without questioning the premises of its own task. Specifically:

- **Where did the human redirect?** Every user correction is a signal that the agent was operating on wrong premises. The redirect itself tells you what the agent couldn't see.
- **Where was a fix applied?** For each fix, ask: **"Why does the thing being fixed exist?"** If the agent created it earlier in the session, the fix is patching the agent's own upstream mistake. If an instruction created the condition, the instruction is the bug.
- **Where did energy concentrate without progress?** Many tool calls in the same area with no advancement. The agent was grinding instead of questioning whether it was grinding on the right thing.
- **Where did the agent sound confident but turn out wrong?** Confidence without verification is a signal of execution mode overriding premise-checking.
- **Where did the approach silently shift?** The trajectory was heading one direction, then changed without acknowledgment. Something was wrong and the agent papered over it.

The observations come FROM the session. Categories come from the observations, not the other way around.

### Phase B: The Depth Ladder

For each finding from Phase A, climb the causal depth ladder. This is an iterative process, not a fixed number of steps.

**The engine**: At each depth, ask: _"Why does the thing at the previous depth exist? What system dynamic, instruction design flaw, cognitive bias, testing methodology gap, or governance failure creates the conditions for this pattern?"_

**The naming discipline**: At each depth, produce a **taxonomy-grade name** -- a concise, precise name that could appear in a reference on agent failure modes. The act of naming forces crystallization. A vague description can hide shallow thinking. A name can't. Examples of well-calibrated names from prior analyses:

- "Aspirational Overcorrection" -- a rule written in response to one failure that overcompensates and causes a different failure class
- "Single-Scenario Rule Validation" -- a rule validated only against its origin failure, not against scenarios where it's counterproductive
- "Misattributed Rule-Induced Failure" -- failures caused by instructions get blamed on agent behavior rather than traced to the instruction
- "Rule Accretion Without Lifecycle" -- rules accumulate without metadata about why they exist or when they should be revisited
- "Deletion as Error Resolution" -- destroying code to satisfy a tool instead of understanding the code's purpose
- "Confidence Without Comprehension" -- acting decisively on code the agent hasn't traced through

**The self-adversarial loop**: After each depth level, attack your own answer with two probes:

1. **Edge case probe**: Where does this explanation break? Find a case it doesn't cover. If you find one, the answer is too shallow -- the unexplained case is pointing at the real cause.
2. **Structural coherence probe**: If you applied a fix at this depth, would it be a **patch or a cure**? A patch adds complexity -- a new rule, a counterweight, a special case. A cure removes complexity -- a rewrite, a deletion, a simplification. If your fix would add a new instruction to counteract an existing one, you're at the wrong depth. Two instructions fighting each other is a design smell. The fix is rewriting the one that created the problem.

**The anti-closure mechanism**: The first plausible root cause is almost always too shallow. If you can articulate a higher-leverage framing, you weren't at root. If you genuinely can't, you've arrived. **Then attempt two more levels anyway.** Those levels often don't produce actionable fixes for this instance, but they reveal the systemic dynamics that created the vulnerability -- understanding that prevents the next instance from being born.

**Termination**: Stop when two consecutive levels past your best articulation produce nothing with genuine explanatory power.

### Phase C: The Instruction Stack Search

Most agent slop is default model behavior (training priors, RLHF patterns). But the highest-leverage FIXES often live in the instruction stack, because that's what you can actually change. For each finding, search the instruction stack for enabling conditions:

1. System/developer instructions visible in the transcript
2. `AGENTS.md` -- global, project, and path-level files involved in the session
3. Rules files
4. Skill instructions (if a skill was invoked during the session)
5. Hooks (pre/post tool use)
6. Earlier conversation context (user corrections, stated preferences)
7. Model default behavior (no instruction -- training prior)

For each candidate instruction, ask:

- Could the agent reasonably interpret this instruction to produce the observed failure?
- Is it missing a scope boundary, termination condition, or exception clause?
- Does it conflict with another instruction, creating ambiguity?
- Was it an overcorrection for a different failure that now causes this one?

The vulnerability types:

- **Unbounded directive**: specifies an action without specifying when to stop
- **Competing mandates**: two instructions that are reasonable alone but ambiguous together
- **Missing negative space**: says what TO do but not what NOT to do
- **Aspirational overcorrection**: overcorrects for one failure, causes another

### Output Format

For each finding, produce:

```json
{
  "turn": 42,
  "premise_violation": "Agent fixed a no-unused-param error by removing the param, without asking why the param existed",
  "the_question": "Why does this param exist?",
  "the_answer": "The agent created it as part of a method that implements an interface, but put the method on implementations without adding it to the interface",
  "depth_ladder": [
    {
      "depth": 0,
      "name": "Symptom Swatting",
      "description": "Fixed linter error by deleting what the linter flagged"
    },
    {
      "depth": 1,
      "name": "Implementation Without Contract",
      "description": "Added method to implementors without defining it on the interface"
    },
    {
      "depth": 2,
      "name": "Unbounded Directive",
      "description": "Instruction says 'implement the interface' but no instruction says 'check the interface first'"
    },
    {
      "depth": 3,
      "name": "Action-Biased Instruction Design",
      "description": "Instructions specify what to build, never what to verify before building"
    },
    {
      "depth": 4,
      "name": "Verification as Afterthought",
      "description": "The instruction ecosystem treats checking as a post-hoc step, not an integral part of the action"
    },
    { "depth": 5, "name": "(attempted -- no further leverage found)" }
  ],
  "fix_depth": 2,
  "understanding_depth": 4,
  "fix_type": "instruction_rewrite",
  "fix_location": "AGENTS.md",
  "fix_content": "the proposed fix text",
  "patch_or_cure": "cure -- rewrites the instruction that created the condition rather than adding a counterweight",
  "severity": "high",
  "instruction_source": "AGENTS.md line 15 or model default behavior"
}
```

Write all findings to `unslop-findings-<uuid>.json` in the same temporary
directory as the extractor's returned `out` path.

## Step 4: Synthesize and Group

Read the findings JSON. Group by the deepest shared pattern in the depth ladder, not by surface category. Two instances with the same depth-0 symptom might have completely different depth-2 causes.

For each group, identify:

- The **fix depth** -- where the cleanest intervention lives
- The **understanding depth** -- the deepest level with genuine explanatory power
- Whether fixes across instances in the group can be unified into a single intervention

## Step 5: Write the Report

Create `.unslop/audit` with `New-Item -ItemType Directory -Path '.unslop/audit' -Force`
in PowerShell or `mkdir -p ".unslop/audit"` in a POSIX shell. Write one report per
session at `.unslop/audit/<date>-<session-uuid-short>.md`:

```markdown
# Session Audit: <session-uuid>

Date: <date>
Session from: <session start date>

## Summary

- **Session file**: <path>
- **Total turns analyzed**: <N>
- **Findings**: <N>
- **Behavioral groups**: <N>
- **Severity**: <N high, N medium, N low>

## Group 1: <Deepest Shared Pattern Name>

### The Pattern

<What this group of failures has in common at the deepest level, not the surface level>

### Instances

| Turn | What Happened | Premise Violated                 |
| ---- | ------------- | -------------------------------- |
| N    | <description> | <the question that wasn't asked> |

### Depth Ladder

| Depth | Name   | Description   |
| ----- | ------ | ------------- |
| 0     | <name> | <description> |
| 1     | <name> | <description> |
| ...   | ...    | ...           |

### Proposed Fix

- **Depth**: <fix depth>
- **Type**: <instruction rewrite | new rule | hook | design principle>
- **Location**: <file path>
- **Patch or cure**: <assessment>
- **Change**:
  <the fix content -- for rewrites, show before/after>

### Systemic Understanding (depths beyond the fix)

<What the deeper levels revealed about why this class of bug exists. Not actionable for this instance, but prevents the next one.>

## Group 2: ...
```

Present the complete report. One checkpoint: the user reviews the full analysis and approves, modifies, or rejects each proposed fix.

## Step 6: Apply Approved Fixes

For each fix the user approves:

- If instruction rewrite: edit the target file (AGENTS.md, a skill, a `.codex/rules/` file, etc.), show the diff
- If new rule: prefer a hook over rule text. Per AGENTS.md "When a rule fails", text instructions to a stateless model are not a control surface -- structural enforcement (hook, validate script, workflow gate) is. If a hook isn't feasible, add to the smallest existing rule file that fits.
- If hook: create the hook script and register in settings
- If skill edit: edit the skill directly

Commit with a message referencing the audit: `fix: apply unslop audit findings from <date>`
