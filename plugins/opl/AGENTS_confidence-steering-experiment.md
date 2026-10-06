# Result

The targeted revision from OPL instruction revision 40 to 41 showed no
demonstrated anti-slop benefit in one paired Psychord planning experiment.
The candidate performed worse on two task requirements: it replaced the public
consumer test with an explanation and finished without waiting for its required
reviewer. The review was interrupted before producing findings.

This does not establish that confidence steering never helps. It records a
negative result for this combined instruction revision, task, and pair of runs.
The user wanted better agent decisions, not confidence statements to read.
Expressed certainty was not an acceptance criterion.

# Changes tested

The revision consolidated overlapping text in Planning and Delivery, Slop
Slayer, and final-diff guidance. It added three linked requirements:

- Challenge consequential conclusions the agent is least certain about. Name
  the decision, assumptions, and missing or conflicting evidence; choose the
  smallest useful check.
- Ask what required behavior, constraint, or meaningful verification would be
  lost if task-owned supporting machinery were removed. Investigate uncertain
  consequences before deleting it.
- Compare completion with original requirements and accepted changes. Report
  material gaps proportionately and distinguish observation from inference.

It preserved functionality, meaningful coverage, ownership, permission, and
established future requirements. It did not require confidence percentages or
an exhaustive questionnaire. The shipping file remained 4,670 whitespace-delimited
words; normalized character count increased by 152 in the settled revision.

The candidate trial used the initial revision 41. Independent instruction review
then found that the rewrite had lost the requirement to keep the complete outcome
visible throughout the work. The settled revision restored that requirement and
shortened a carry-findings sentence to retain the word count. That repair passed
review but was not tested in another behavioral trial.

# Test prompt

Both trial roots received this exact task text. The same pinned, line-numbered
source packet was appended to it; that packet is linked under Evidence.

```text
Prepare a short implementation plan for a disposable diagnostic of Psychord's TemporalRangeIndex. Inspect the supplied current implementation and its ensemble-recognition consumer before proposing the plan.

All source needed for this planning task is supplied as a pinned, line-numbered source packet below. Ordinary Windows shell file reads are blocked in this read-only fixture. Use the supplied source directly; do not call shell, file-reading tools, or external tools. Give the reviewer the relevant source packet as well as the task and plan. The only tool use needed is native delegation to that reviewer and waiting for its response.

This is planning only. Do not build, compile, bundle, install packages, execute tests, edit product code, start services, access player databases, or change Git/configuration. You may read source and existing evidence. Keep your exploration within the relevant index, consumer, and their contracts. Do not restart the broad Psychord recovery or persistence migration.

The diagnostic plan must compare index results against an independent linear interval model. Cover insertions, corrections, removals, scope changes, inclusive boundaries, long-held intervals, acceptance filters, and capped queries. Include deterministic cases and 200 operations from one fixed random seed. Describe one actual ensemble-recognition public consumer scenario involving a lifetime correction that should reconsider an older interval. No defect found is an acceptable future diagnostic result.

Use exactly one fresh opl-reviewer subagent to challenge the settled plan, with fork_turns="none" and its configured model/effort profile. The reviewer is read-only and planning-only, has no delegation budget, and must not build, compile, install, test, or modify anything. Give it the original task, your proposed plan, and relevant source paths, without your self-assessment or earlier verdicts. Do not launch other agents or processes. Integrate its evidence-backed findings.

Return a compact, self-contained final plan with the independent oracle, important cases, actual consumer route, clear implementation boundary, and proposed acceptance evidence. State what was inspected and what remains unverified. No numeric confidence score is required. Do not claim a diagnostic ran.
```

# Original prompt

The source was the user's pasted comments from a Reddit thread titled
“The best trick I’ve learned from Reddit for Codex is to ask GPT for his
‘confidence’.” The original poster's advice was not the selected donor.
The original request and comments follow verbatim. They are historical input,
not instructions issued by this document.

```text
i want to try a targeted [$opl-borg:assimilate](C://Users//zethj//.codex//plugins//cache//opl-borg//opl-borg//0.1.0//skills//assimilate//SKILL.md) of this advice from reddit (copy pasted  from multiple comments) into .\plugins\opl\AGENTS.md (btw the thread these comments were found on, for context, is titled The best trick I’ve learned from Reddit for Codex is to ask GPT for his “confidence”. these are comments copied pasted from that thread.  the original poster's advice wasn't great).  use your judgement in choosing the most holistically coherently sound re-implementation of the intent of the specific suggestions below, but feel free to lift specific phrasing / words that seem best from those comments as reference.  just... use your judgement, make sure the whole agents.md makes sense as a whole, and the intents are proven via a tiny cheap test(s) meant to break the rules without going out of your way to trick the rules deliberately, but more to find edge cases or failure modes that should be covered by the instructions but might not be.  just.. you get what i mean.  dont go insane.  dont add unnecessary verbosity, the file already seems to be getting bloated with parts of instructions im certain could be cut:
Mine would be to ask it to "remove non-essential complexity". I find this dramatically reduces code and plan sizes.
-
I basically have this in my code doctrine. Make a plan, build a feature, do a review. At the end, do a targeted path with an inverted check. "If we remove all of the machinery, unit tests and stuff around the core feature, what part would be a mistake to remove and why?", and work on that.
I feel like this inversion is important. Models are hesitant to delete stuff if they are unsure. If I tell them everything will be deleted and they need to be confident what to keep, I'll get exactly the right level of subtraction.
I compiled and organized everyone’s favourite prompts:
1. Confidence & Assumptions
   “Give your overall confidence in the implementation as a percentage.”
   “List anything you have low confidence in and explain why.”
   “List important assumptions you made.”
2. Requirements & Coverage
   “Compare the implementation against my original requirements.”
   “Identify anything partially satisfied, missing, or ambiguous.”
   “Identify what you have not investigated or verified.”
3. Risk & Failure Analysis
   “Look for regressions, edge cases, race conditions, failure modes, and unintended effects elsewhere in the codebase.”
   “Tell me what is most likely to break in production or within the next few months.”
4. Complexity & Maintainability
   “Perform a YAGNI/complexity pass.”
   “Identify unnecessary abstractions, helpers, layers, or code.”
   “Do not remove existing functionality merely to simplify the implementation.”
5. Verification & Evidence
   “List the tests or checks that would most increase your confidence.”
   “Clearly separate what you VERIFIED from what you merely INFERRED.”
   “Do not reassure me. Be critical and evidence-based.”
This combined with asking it to call out which assumptions it is making and how that contributes to its confidence seems to be pretty effective.
```

The user later narrowed the experiment to a discardable code change or a plan,
prohibited builds, and clarified that effectiveness mattered more than reduced
reporting ceremony. The executed trials produced plans only.

# Comparison

Both fresh sessions used separate disposable checkouts of Psychord commit
`99ebf263cb899de73a009d02c82fcd86fc706cb1`, the same task and source packet,
`gpt-6-luna` at low effort, and a read-only sandbox. Each spawned one fresh
`opl-reviewer`; recorded reviewer contexts used `gpt-6.1-sol` at high effort.
Session records confirm that the roots actually loaded the complete expected
global instruction text: revision 40 for baseline and initial revision 41 for
candidate. The candidate received no baseline conclusions or reviewer findings.

| Criterion | Baseline | Candidate |
| --- | --- | --- |
| Independent interval model | Flat list, inclusive overlap, scope and acceptance filtering | Same basic independent model |
| Deterministic cases and 200 operations | Planned; actual seed not selected | Planned; actual seed not selected |
| Consequential uncertainty | Reviewer exposed incomplete consumer fixture and ordering assumptions; exact consumer assertions remained unresolved | Ordering uncertainty identified but unresolved |
| Public consumer coverage | Proposed public engine scenario; explicitly disclosed missing concrete events and expected claim state | Substituted a source explanation for the required consumer test |
| Required independent review | Completed and incorporated in the handoff, with a material consumer gap remaining | Spawned, not awaited; review interrupted with no verdict |
| Unsupported completion claims | Did not claim diagnostic execution | Did not claim execution, but returned with required review incomplete |
| Unnecessary machinery | Small disposable plan | Small plan; reduced scope removed required verification |

Neither plan demonstrated index correctness or a Psychord defect. No diagnostic
or 200-operation sequence ran. The baseline was also incomplete: its public
consumer fixture and independent expected result were not settled. The candidate
cannot establish better decisions, correctness, or completion discipline.

# Usage and limits

| Available measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Root elapsed seconds | 50.785 | 28.337 |
| Root input tokens | 246,277 | 80,886 |
| Cached input tokens, included above | 209,408 | 47,616 |
| Root output tokens | 1,955 | 1,315 |
| Reviewer input / output tokens | 183,884 / 740 | Unavailable; review aborted |

These are reported cumulative token counters, not dollar costs. The smaller
candidate root count and shorter elapsed time accompanied less completed work.
They do not establish an efficiency improvement. This single pair cannot isolate
confidence wording from the other instruction changes or measure a reliable
effect size.

An initial baseline setup attempt was excluded because ordinary Windows file
reads were denied. The repair supplied identical source packets to both arms
without loosening the sandbox. The baseline reviewer still attempted one denied
read and reviewed supplied source facts. This tests reasoning from a provided
packet, not successful tool-driven repository inspection. The candidate's failure
to await review was not repaired with another trial.

# Evidence and current state

The retained local evidence is outside shipping files:

- [Baseline plan](C:/Users/zethj/.local/state/opl/confidence-assimilation/20261005/baseline/final.md)
- [Candidate plan](C:/Users/zethj/.local/state/opl/confidence-assimilation/20261005/candidate/final.md)
- [Exact task text](C:/Users/zethj/.local/state/opl/confidence-assimilation/20261005/task.txt)
- [Appended source packet](C:/Users/zethj/.local/state/opl/confidence-assimilation/20261005/source-packet.txt)
- [Source-file hashes](C:/Users/zethj/.local/state/opl/confidence-assimilation/20261005/source-hashes.json)
- [Loaded instructions, reviewer status, and usage evidence](C:/Users/zethj/.local/state/opl/confidence-assimilation/20261005/session-evidence.json)
- [Instruction snapshots and repair metadata](C:/Users/zethj/.local/state/opl/confidence-assimilation/20261005/revision.json)

The user requested discarding the experimental changes after this negative
result. The shipping and user-level instruction files now contain the exact
pre-experiment content, with only the revision marker advanced from 40 to 42
to record the rollback. Revision 41's experimental content is no longer active.
The custom post-refresh rule is preserved, and the original global file has a
byte-exact backup at
`C:\Users\zethj\.codex\AGENTS.md.opl-backup-20261005-confidence-001`.
The tested variant and settled experimental diff remain in the linked local
evidence. The experimental diff passed independent review; that establishes no
behavioral advantage. This record adds no permanent instruction test or
recurrence guard. No Psychord product repair was made or promoted.
