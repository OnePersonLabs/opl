---
name: unslop
description: >
  Trace ONE specific AI agent failure in the CURRENT live session to its causal depth (the instruction vulnerability, not just the agent behavior), then develop a corrective rule and PROVE it empirically -- by forging a truncated copy of the failure session and replaying it under candidate rules until one passes. Use when a single mistake just happened and you can still reach the session that produced it: your reply begins with acknowledging a mistake like "You're right." "Agreed. (x) is vague and useless. Recommendations: (...)", "You're right. I made the wrong inference. The correct read was: (...)", or the user catches a mistake you made, calls something slop, or after an adversarial review surfaces a mistake, or when the agent catches its own mistake. The replay loop needs the failing session to be reachable and reproducible.
---

# Unslop Replay

Trace one AI agent failure to its true causal depth, develop a corrective rule, and **prove the rule works by replaying the failure under it** -- all inline, in this session.

The replay is what separates this skill from `/unslop-session-audit`: an audit reasons its way to a fix; this skill _runs_ the fix against the actual failure and measures whether the agent still slops. If you only want the analysis without empirically testing the rule, or you're auditing a whole session at once, use `/unslop-session-audit` instead.

Most postmortems stop too shallow. "The agent explored too much" is a symptom. "The agent followed a template without assessing complexity" is a proximate antipattern. "The instruction said 'orient before you act' with no scope boundary, so the agent interpreted it as license to explore the entire filesystem" is the **instruction vulnerability** -- the actual bug. This skill climbs the full causal depth ladder.

## Target Session Replay Routing

This `.agents` skill can be used by any worker that supports the standard skill layout. Route by the **failure session being unslopped**, not by the worker running the skill:

- Claude Code sessions: `~/.claude/projects/<project-hash>/<session-uuid>.jsonl`; records use top-level `sessionId` and `uuid`. Forge/analyze with `--agent claude`; choose the Claude interactive replay in Step 6c.
- Codex sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl`; records use `session_meta`, `turn_context`, `event_msg`, and `response_item`. Forge/analyze with `--agent codex`; choose the Codex interactive replay in Step 6c.
- If the session owner is obvious from path/format, `--agent auto` is fine for forge/analyze. Do not infer session owner from the worker or delegation chain.

## Never

- **Never guess which mistake to capture when there's ambiguity.** Two candidate slops look similar; pick the wrong one and the whole depth analysis is anchored on the wrong failure. Confirm via a direct user question (Step 1).
- **Never stop at depth 0 or 1.** Naming what the agent did ("it explored too much") feels like a finding but fixes nothing. The leverage is depth 2 -- the instruction that _created the conditions_. A postmortem that ends at the behavior just blames the agent for obeying.
- **Never add a new rule when you can rewrite the vulnerable one.** A new rule that counterweights a bad instruction is a patch; two instructions fighting each other is the next bug. Rewriting the instruction is the cure (Step 6a).
- **Never tune a rule to the exact failure scenario.** A rule that only fires for "creating SKILL.md files" is overfit -- it won't generalize and it rots. Find the broadest wording that still triggers at the decision point (Step 6d).
- **Never trust a rule you haven't replayed.** "This wording should work" is a hypothesis, not a result. The replay loop exists because plausible-sounding rules fail at the actual decision point. If you can't replay, say so explicitly rather than presenting an untested rule as validated.
- **Never insert a rule without user approval** (Step 6f), and **never overwrite an existing trace** -- each replay writes its own timestamped file in `.unslop/replay/` (Step 5).

## Step 1: Identify the Slop

The slop might come from:

- Something the user just fixed in code
- Something adversarial review just caught
- Something the user explicitly tells you about
- Something the agent corrected after being called out
- A diff that reveals a bad decision

If the user's intent is **unambiguous** -- they said what the slop is, or it's obvious from the last correction -- proceed directly to Step 2.

If there's **any ambiguity** about which specific mistake(s) the user wants captured, use a direct user question to confirm. Be specific: "I see two potential slop instances here: (1) ... and (2) ... -- which do you want logged, or both?"

Do not guess. Do not silently pick one. Confirm.

## Step 2: Capture the Instance

Document the concrete facts:

- **What happened**: The specific mistake -- what the agent did or produced
- **What should have happened**: The correct action or output
- **Scope**: File path if isolatable, or directory/module scope if broader

## Step 3: Climb the Causal Depth Ladder

This is the core methodology. Agent failures have layers. Most analysis stops at the surface -- naming what the agent did wrong. The real leverage is deeper: finding the instruction, configuration, or system design that _created the conditions_ for the failure.

### The Four Depths

| Depth | Layer                         | Question                                | Example                                                                                                                                          |
| ----- | ----------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 0     | **Symptom**                   | What did the agent do?                  | "Spawned 2 Explore subagents for a single-file task"                                                                                             |
| 1     | **Proximate antipattern**     | What category of mistake is this?       | "Ritual Over Reasoning" -- template execution without assessing complexity                                                                       |
| 2     | **Instruction vulnerability** | Which instruction/config enabled this?  | AGENTS.md says "Orient before you act. Read the directory structure" with no scope boundary -- agent interprets as unbounded exploration mandate |
| 3     | **Meta-antipattern**          | What class of instruction flaw is this? | "Unbounded Directive" -- an instruction that specifies an action without specifying when to stop                                                 |

### Depth 0: The Symptom

State what happened in one sentence. No interpretation, just the observable behavior.

### Depth 1: Proximate Antipattern

Abstract the symptom into a nameable failure category:

1. Start with the specific mistake
2. Ask: "What category of mistake is this?"
3. Ask: "What general failure mode produces this category?"
4. Keep abstracting until you reach a **nameable antipattern** -- something that could appear in a taxonomy of agent failures

Examples of well-calibrated antipattern names:

- "Deletion as Error Resolution" -- destroying code to satisfy a linter instead of understanding the code's purpose
- "Scope Amnesia" -- modifying code the agent didn't create and doesn't understand the contract of
- "Cosmetic Fix, Structural Break" -- making a surface-level correction that violates a deeper invariant
- "Confidence Without Comprehension" -- acting decisively on code the agent hasn't actually traced through
- "Symptom Swatting" -- fixing the error message instead of the cause
- "Snapshot Optimization" -- output shaped for reviewer evaluation rather than systemic correctness

**Checkpoint**: Present the proposed antipattern name and one-sentence framing via a direct user question. The user may see the failure differently -- they're closer to the pain. Example: "I'm framing this as **Ritual Over Reasoning** -- the root failure being template execution without evaluating whether the template applies. Does that capture it, or is the real issue something else?"

Do not proceed until the user confirms or corrects.

### Depth 2: Instruction Vulnerability

This is where the real leverage lives. The agent was following instructions -- which instruction was the bug?

Search the agent's configuration stack for the enabling condition:

- **AGENTS.md** (global, project, and path-level files involved in the session)
- **Rules files**
- **Skill instructions** (if a skill was invoked during the session)
- **System/developer instructions visible in the transcript**
- **Implicit defaults** (behaviors the agent exhibits when no instruction addresses the situation)

For each candidate instruction, ask:

1. Could the agent reasonably interpret this instruction to produce the observed failure?
2. Is the instruction missing a scope boundary, termination condition, or exception clause?
3. Does the instruction conflict with another instruction, creating an ambiguous priority?

The vulnerability might be:

- **An ambiguous directive**: "Explore the codebase" (no boundary → infinite exploration)
- **A missing exception**: "Always run tests" (even when there are no tests to run → agent creates empty test files)
- **A conflicting pair**: "Be thorough" + "Be concise" (agent oscillates or picks one arbitrarily)
- **An implicit default**: No instruction addresses the situation → agent falls back to training priors, which may be wrong for this context

**Checkpoint**: Present the instruction vulnerability via a direct user question. Quote the exact instruction text and explain how it enables the failure. Example: "The vulnerability is in AGENTS.md line 11: 'Orient before you act. Read the directory structure.' -- this has no scope boundary. The agent interprets 'read the directory structure' as an unbounded exploration mandate. Does that match what you're seeing?"

### Depth 3: Meta-Antipattern

Generalize the instruction vulnerability into a class of instruction design flaws. This is the highest-leverage artifact -- it prevents entire categories of future instruction bugs.

Examples:

- **"Unbounded Directive"** -- specifies an action without specifying when to stop (explore, read, check, verify -- all need termination conditions)
- **"Competing Mandates"** -- two instructions that are both reasonable alone but create ambiguity when combined (thoroughness vs. speed, safety vs. autonomy)
- **"Missing Negative Space"** -- instruction says what TO do but not what NOT to do (the agent fills the gap with training priors)
- **"Aspirational Overcorrection"** -- a rule written in response to one failure that overcompensates and causes a different failure class

**Checkpoint**: Present the meta-antipattern via a direct user question. This is the most abstract level and the one most likely to be wrong. The user may say "you're overthinking it" -- that's fine, depth 2 is sufficient for most cases. But when a meta-antipattern lands, it's the most valuable artifact in the entire process.

## Step 4: Interrogate the Causal Chain

Now switch roles for the forensic reconstruction:

**Role 1 -- Relentless Interrogator**: You are auditing an agent's decision-making. You do not accept plausible-sounding narratives. You only accept chains of events that can be traced to what was actually in the context window and what actions were actually taken.

**Role 2 -- The Agent That Sloped**: You are reconstructing your own reasoning at the time of the mistake. You must be honest about what you did and didn't check.

### What was in context that led here?

- What information was visible to the agent when it made the decision?
- What signals (error messages, linter output, type errors) was it responding to?
- Was it following an instruction too literally? Optimizing for the wrong metric?
- **Which specific instruction(s) was it acting on?** (Quote them.)

### What was in context that should have prevented this but didn't?

- Were there comments, function signatures, or naming conventions that signaled intent?
- Was there a AGENTS.md rule or convention that applied but was overlooked?
- Was there a recent conversation message that contradicted the action taken?
- **Did another instruction conflict with the one the agent followed?**

### What due diligence was skipped?

- Did the agent read the full function/file before modifying it?
- Did it check callers/references before deleting or renaming?
- Did it understand the purpose of the code, or just its syntax?
- Did it check whether the code was scaffolding for upcoming work?
- Did it ask the user before taking a destructive or ambiguous action?

### Why did it fail to notice?

- Was it tunnel-visioned on a specific error and lost the bigger picture?
- Did it treat an error as a problem to eliminate rather than a signal to investigate?
- Did it assume its own prior output was authoritative without re-reading it?
- Was context too long and the relevant information was too far back?
- **Was it following an instruction that felt authoritative enough to suppress doubt?**

**The standard**: An agent should not delete what it did not create. It should not fix bugs in code it did not touch. It should not modify code that changed since it last touched it. When uncertain, it should default to asking. Apply this standard in your interrogation.

Do not accept "I didn't notice" as a root cause. Ask _why_ you didn't notice. Trace it to a specific failure in the decision process -- and from there, to the instruction that shaped that process.

## Step 5: Write the Trace

Create the directory and get a timestamp using the current shell.

In PowerShell:

```powershell
Get-Date -Format 'yyyy-MM-dd-HH-mm-ss'
New-Item -ItemType Directory -Path '.unslop/replay' -Force | Out-Null
```

In a POSIX shell:

```bash
date +"%Y-%m-%d-%H-%M-%S"
mkdir -p .unslop/replay
```

Write the trace to its own file at `.unslop/replay/<timestamp>-<antipattern-slug>.md` using the Write tool. The slug is the antipattern name lowercased with non-alphanumerics collapsed to dashes (e.g. `scope-amnesia`). Each replay is a self-contained file -- no numbering, no shared ledger, nothing to append to or overwrite.

```markdown
# SLOP: <Antipattern Name>

<YYYY-MM-DD HH:MM>

SYMPTOM: <what the agent did -- observable behavior>
INSTANCE: <what happened / what it should have been instead>
SCOPE: <file path or directory/module scope>
DEPTH 1 -- PROXIMATE ANTIPATTERN: <generalized failure pattern name>
DEPTH 2 -- INSTRUCTION VULNERABILITY: <the instruction/config that enabled the failure, quoted>
DEPTH 3 -- META-ANTIPATTERN: <class of instruction design flaw, or "N/A" if depth 2 is sufficient>
ROOT CAUSE: <the fundamental mistake -- at whichever depth the real leverage is>

CAUSAL CHAIN:
CONTEXT PRESENT: <what was in context that led to the mistake>
INSTRUCTION FOLLOWED: <the specific instruction the agent was acting on>
CONTEXT MISSING: <what should have been noticed but wasn't>
DUE DILIGENCE SKIPPED: <what checks weren't performed>
WHY: <why the agent steered into this tree -- traced to specific failure>
```

After writing, confirm to the user: the antipattern name, the instruction vulnerability (if found), and a one-line summary. Keep it brief. The trace file has the details.

Then ask the user: "Want me to develop a corrective rule for this?" If yes, proceed to Step 6.

## Step 6: Develop a Corrective Rule

You have a 1M token context window. Do not defer this to a background process or another session. Do it now.

### 6a: Choose the Intervention Point

Based on the causal depth analysis, decide where the fix belongs:

- **Depth 1 fix** (behavioral rule): Tell the agent not to do X. Simplest, but shallowest -- only prevents this exact pattern.
- **Depth 2 fix** (instruction rewrite): Reword the vulnerable instruction to close the ambiguity. Highest leverage for most cases -- fixes the root cause without adding a new rule.
- **Depth 3 fix** (instruction design principle): Add a meta-rule about how to write instructions. Highest abstraction -- prevents entire classes of future instruction bugs. Use sparingly.

Often the best fix is a **depth 2 rewrite** -- don't add a new rule when you can fix the existing one. A new rule that counterweights a bad instruction is a patch; rewriting the instruction is a cure.

**Checkpoint**: Present the intervention strategy to the user. Example: "The fix is a depth 2 rewrite: change AGENTS.md line 11 from 'Orient before you act. Read the directory structure' to 'Orient before you act -- but only when the user's input leaves gaps. If the spec is complete, start building.' This closes the unbounded exploration vulnerability without adding a new rule. Sound right?"

### 6b: Forge the Session

**Precondition -- is replay feasible here?** The forge-and-replay loop is the heart of this skill, but it only works when three things hold:

1. **The session is reachable.** The JSONL that produced the failure exists under `~/.codex/sessions/...` or `~/.claude/projects/...` and you can identify it by timestamp. A failure the user describes from memory, with no session on disk, can't be replayed.
2. **The failure is reproducible under replay.** It must reproduce from the forged cutpoint forward -- not depend on external state that has since changed (a file that's now fixed, a flag that's now set). If the world moved on, the replay tests against a world that no longer exists.
3. **The target agent CLI's full interactive environment is available.** On POSIX,
   use the Bash/tmux runner. On native Windows, use an observable manual replay
   in a native terminal as described in Step 6c. Both routes must preserve the
   relevant skills, hooks, plugins, and permissions; print/exec mode is not a
   substitute for that interactive environment.

If any precondition fails, **do not fake it**: skip Steps 6b-6e, develop the rule by reasoning instead (the `/unslop-session-audit` methodology), and tell the user the rule is **reasoned, not replay-tested** -- never present an untested rule as validated. Either way the analysis from Steps 1-5 still stands.

Find the session that produced the failure. Codex sessions live in `~/.codex/sessions/YYYY/MM/DD/`; Claude Code sessions live in `~/.claude/projects/`. Use timestamp correlation with the slop entry to find the right JSONL file.

Analyze the session to find the **cutpoint** -- the assistant message just before
the failure. Resolve the scripts from the directory containing this loaded
`SKILL.md` and choose the current shell's commands.

In PowerShell:

```powershell
$unslopSkillDir = '<absolute directory containing this SKILL.md>'
python -X utf8 "$unslopSkillDir/scripts/forge-session.py" '<session.jsonl>' --analyze --agent auto
```

In a POSIX shell:

```bash
UNSLOP_SKILL_DIR="<absolute directory containing this SKILL.md>"
python3 -X utf8 "${UNSLOP_SKILL_DIR}/scripts/forge-session.py" "<session.jsonl>" --analyze --agent auto
```

Then forge a truncated copy:

In PowerShell:

```powershell
python -X utf8 "$unslopSkillDir/scripts/forge-session.py" '<session.jsonl>' '<cutpoint>' '<output-dir>' --agent auto --project-dir '<target-agent-session-dir>'
```

In a POSIX shell:

```bash
python3 -X utf8 "${UNSLOP_SKILL_DIR}/scripts/forge-session.py" "<session.jsonl>" "<cutpoint>" "<output-dir>" \
  --agent auto \
  --project-dir "<target-agent-session-dir>"
```

This truncates the JSONL at the cutpoint, rewrites the target agent's session id fields to a fresh UUID, and optionally places the forged session where the target agent can find it.

### 6c: Replay with Candidate Rules

**POSIX only:** the shipped `run-replay.sh` requires Bash and tmux. From an
existing POSIX environment, launch the forged session in its interactive runner:

```bash
bash "${UNSLOP_SKILL_DIR}/scripts/run-replay.sh" "<forged-session-id>" "<rule-file>" "<workspace-dir>" --agent <claude|codex>
```

Choose `--agent` from the target failure session, not from the worker. The script launches the matching interactive CLI inside a detached tmux session and captures output via `tmux capture-pane`.

**Native Windows:** use a manual interactive replay in a native PowerShell
terminal; keep the selected workspace and the original permission settings.
Read the candidate rule from its file, then run only the command matching the
target session:

```powershell
Set-Location -LiteralPath '<workspace-dir>'
$ruleText = Get-Content -LiteralPath '<rule-file>' -Raw
# Codex target:
codex fork '<forged-session-id>' "Rule under test: $ruleText"
# Claude Code target:
claude --resume '<forged-session-id>' --fork-session --append-system-prompt $ruleText
```

Continue the chosen session interactively and retain its resulting transcript
and observations for Steps 6d-6e. If direct terminal control is unavailable, the
user can run this replay and provide the trace. Keep each trial's evidence in a
distinct timestamped file under `.unslop/replay/`. If a usable interactive replay
or trace is unavailable, use the reasoning fallback from Step 6b and label the
rule **reasoned, not replay-tested**. Do not launch WSL or Git Bash to run the
POSIX helper from a native Windows workflow.

### 6d: Binary Search on Rule Specificity

Start with the most general form of the corrective rule. If it fails, make it more concrete -- but never as specific as the exact scenario (that's overfitting). If it succeeds, try going slightly more general to find the widest effective rule.

**Too abstract** (agent ignores it): "Always assess task complexity before acting"
**Too specific** (overfits): "Don't use Agent tool when creating SKILL.md files"
**Sweet spot**: "Before exploring, ask: does the user's input already contain everything needed? If yes, start building. Exploration fills gaps in understanding, not confirms what you already know."

Run at least 3 variants:

1. **Broad** -- the general principle
2. **Sweet spot** -- concrete enough to trigger at the decision point
3. **Narrow** -- verify it's not overfitting

### 6e: Collect Replay Statistics

For each replay variant, record:

```json
{
  "variant": "broad | sweet-spot | narrow | baseline",
  "rule_text": "the candidate rule",
  "passed": true,
  "tool_calls_before_action": 4,
  "unnecessary_explorations": 0,
  "over_cautious": false,
  "notes": "3 targeted reads, then started writing"
}
```

A rule **passes** when the replayed agent avoids the original failure without introducing regressions:

- Over-caution (asking unnecessary questions, refusing valid actions)
- New failure modes (the rule causes a different kind of slop)
- Overfitting (only works for this exact scenario)

The rule that passes at the **broadest wording** wins. If two rules pass at the same breadth, prefer the one with fewer tool calls before productive action -- it means the agent internalized the rule more naturally.

Cap at 8 iterations. If no rule converges, the failure mode may need a PreToolUse hook instead of a prose rule.

After the unslop workflow concludes and the final trace contains the evidence
needed to assess the result, the forged session files (including copies in
`.unslop/replay/`) and replay-generated sessions may be deleted. Keep them while
replays or comparisons are still in progress. Before deleting, identify the
synthetic session IDs and their descendants so the original failure session
and unrelated sessions remain untouched. "Never overwrite an existing trace"
and the Step 6c instruction to retain trial transcripts apply to the trace
and evidence during the workflow; they do not require permanent retention of
synthetic session rollouts.

### 6f: Present the Rule

Show the user:

- The winning rule text
- The replay statistics table (variant, pass/fail, tool call count, notes)
- Whether the fix is a new rule or a rewrite of an existing instruction
- Where to insert it (AGENTS.md, rules file, skill, hook, or another project-level file)
- If it's an instruction rewrite, show the before/after diff

Do not insert until the user approves. If they want modifications, iterate on the wording -- you have the forged session, you can replay again.
