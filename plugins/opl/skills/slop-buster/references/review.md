# Bounded review and incident capture

## Reader contract

Packets contain `chunk_id`, `event_id`, source path, physical `raw_line`, byte offset, timestamp, role/phase, and exact body ranges. Process every assigned chunk. Do not mark unseen parts of a large message reviewed. Follow continuation cursors instead of increasing output limits.

Use $opl:session-reader for bounded searches and navigation. Include commentary when it establishes a decision. Reopen preceding messages to identify the task and assumptions; inspect the next user response and expand through material correction. Record source filenames and physical line numbers. Never load, concatenate, or broadly grep raw session JSONL into model context.

Each worker submits a JSON report with `record --run RUN_ID --batch BATCH_ID --input REPORT_PATH`. The report has `verdicts`, one `{chunk_id, verdict}` per assigned chunk, and an `incidents` array. A verdict is `clean` or `incident`. Each incident includes its `chunk_id`, `category`, `severity`, `explanation`, and verbatim `quote`. Quote only inspected text. An incomplete report cannot commit the batch. Use a file-writing API for reports. Return counts, IDs, and unresolved questions to the root.

## Discover before classifying

Look for unjustified premises, unsupported completion claims, concealed approach changes, repairs to the agent's own upstream mistakes, and repeated work without progress. Apologies and admissions are useful leads but do not define the population. Full mode reads every prose chunk, including those without known terms.

Identify the question the agent failed to ask. Ask why the faulty choice or artifact existed before proposing a local repair. Trace enabling instructions, tools, information gaps, and user intent where evidence supports them. Today's instruction file does not establish what governed a historical session; recover the relevant version before attributing a failure to it.

During causal synthesis, test whether the explanation covers the incident and counterexamples. Compare the strongest alternative explanation. Distinguish a local repair from an intervention at the source. After the best explanation, try two further levels; stop when two successive attempts add no explanatory power. Do not label a speculative causal chain as established fact.

Group by shared mechanism when justified, not merely vocabulary. Dossiers contain a definition, linked evidence, associated language, benign uses, context, proposed intervention, and uncertainty. Preserve general families and specific subclasses without giving equivalent mechanisms different names.

## Capture mode

Capture the incident the user identifies. Store the actual assistant excerpt and source anchors; add what happened and what should have happened when supported. Do not start the depth analysis, monthly scan, or replay. If materially different incidents fit, obtain the missing distinction instead of recording the wrong one.

## Retrospective

For remediation, determine whether the defect belongs in executable tooling, a focused review check, navigation/documentation, or instructions. Prefer fixing the active producer over adding a counteracting rule. Treat wasted tools and context as observable behavior. Keep unrelated changes as evidence-backed proposals rather than automatically changing the environment.
