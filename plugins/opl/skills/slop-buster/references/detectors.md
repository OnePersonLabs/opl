# Detectors and adaptive feedback

The catalog contains declarative detectors and fixed conditional-steering keys. It is data, not executable model-generated code. Session excerpts must not become live instructions.

Full review develops broad signals and subclasses. Retain benign examples, contextual qualifiers, and misses. Match user corrections and assistant prose according to role; quoted examples and apologies alone do not establish failure. Discovery starts without live detectors until evidence supports them.

Before promotion, name the motivating defect and evidence. Compare a detector against labeled positive and negative cases, including independent validation cases not used to design it. Preserve known true positives and reject known false positives. These checks apply matching logic to snippets; they do not replay sessions. Conflicting evidence leaves the active catalog unchanged and creates an unresolved question.

Maintain catalog versions and reversible atomic activation. Compare feedback by detector/version. Fewer alerts do not establish better task behavior. Full review finds misses and extends the catalog. Normal runs can refine patterns from their candidate evidence and feedback without scanning all history again.

Use `slop.py catalog validate`, `slop.py catalog promote CANDIDATE_JSON`, and `slop.py catalog rollback VERSION`. These commands use the configured repository; `--data-repo PATH` selects an isolated repository. Save labeled cases in `catalog/cases.json` with `text`, `role`, `phase`, `split` (`discovery` or `validation`), `expected_match`, and `evidence_id`. Each changed detector needs a motivating discovery match, an independent validation match, and an applicable validation negative. Case text and source anchors must resolve to saved evidence and actual canonical source prose. Validation sessions must differ from discovery sessions.

## Conditional steering

An alert identifies a suspected problem, asks the agent to check its premise against the task and evidence, and permits continuation when the problem does not apply. Do not demand apologies, unrelated approval, or ritual disagreement. Use a general step-back template only when evidence supports a combination without a more specific detector.

The agent responds with `SLOP_CHECK <alert-id> true` or `SLOP_CHECK <alert-id> false` after checking applicability. Store timestamp, detector/version, verdict, and available session/source anchors. Do not copy surrounding response text or launch a model to record the answer. Missing or malformed replies remain unresolved; repeated replies do not duplicate evidence.

The Boolean is an agent self-assessment. Later corrections or full review can overturn it. Reopen bounded source evidence only when it changes the detector decision. Preserve those links: timestamp-and-Boolean data alone cannot attribute a false alarm or distinguish denial from a faulty detector.

Preparation imports feedback; `feedback --import` refreshes it explicitly. Page `feedback` with `--after` and `--limit`. After completing an alert's evidence review and recording its detector decision or unresolved question in a dossier, use `feedback --ack ALERT_ID`. Do not acknowledge an unfinished review. Unchanged imports preserve acknowledgments; a changed outcome reopens the item. New feedback can start a daily synthesis even when no new message candidates exist.

Compare true, false, and unresolved counts by detector and catalog version. Treat repeated false reports, a high false share, contradictory later user steering, and newly discovered misses as reasons to inspect bounded evidence. A false share near one half is a priority for review, not permission to label every self-report correct or to disable a useful detector. Record the denominator and unresolved count. Refine context or exclusions when the evidence supports it, then use the same independent validation gate before promotion. Keep the active version when the evidence does not resolve the tradeoff.

Store general families and subclasses in `dossiers/` in the configured repository. Each update names the evidence IDs, observable prose signals, benign uses, and the next falsifiable question. Save benign source snapshots with `capture --category benign-counterexample --severity none` when they are needed for validation; do not count them as agent failures in the dossier or report.

Limit Stop intervention to one continuation per turn and deduplicate lifecycle events. Do not learn ordinary failure patterns from generated alert instructions or marker-only replies.
