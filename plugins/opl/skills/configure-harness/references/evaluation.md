# Bounded behavior evaluation

Read this reference when a configuration decision depends on observed activation, selection, or recovery behavior. Define the test before running it. Do not evaluate every catalog item merely because it appears in inventory.

## Manifest and budget

Create a `plan` spec with candidate versions or content hashes, planned cases, explicit model IDs, and a finite budget. The helper creates the run ID. Each case has an ID, candidate ID, phase (`capability`, `selection`, or `recovery`), concrete scenario, rubric, and explicit `allowedEffects` list. Capability cases use Luna. Selection and recovery cases require `executionModel`: the actual production model intended for that route, which is not automatically Luna. Agree on `maxCases`, `maxToolCalls`, and `maxFollowupCases` before executing. Keep the sum of initial and follow-up cases within `maxCases`; `maxFollowupCases` is no greater than `maxCases`. The helper permits one follow-up batch through `followup --home PATH --run ID --spec PATH` with `{ "reason": "...", "cases": [...] }`. Use it only when ambiguity or inconsistent relevant routing could change the choice. Reuse the bounded Luna executor and Sol evaluator for the follow-up; create fresh contexts for each unaided route case.

For example, an output-only capability case can use this spec. Write the JSON to a file and pass its path to `plan`:

```json
{
  "candidates": {"sample-skill": "1.0.0"},
  "models": {"executor": "gpt-6-luna", "evaluator": "gpt-6-sol"},
  "budget": {"maxCases": 2, "maxToolCalls": 4, "maxFollowupCases": 1},
  "cases": [{
    "id": "capability-1",
    "candidateId": "sample-skill",
    "phase": "capability",
    "scenario": "Answer a bounded request using the reviewed skill in an isolated test context.",
    "rubric": "Identify the requested result and cite the observed output that establishes it.",
    "allowedEffects": []
  }]
}
```

Replace the example candidate version, scenario, and rubric with actual reviewed values. A zero-effect case still counts any tool calls against the budget. The helper records counts but cannot stop an already-running agent; instruct the executor to stop at the limit and stop manually if it exceeds the budget.

A capability test asks whether the option can perform a concrete task with its stated permissions and dependencies. A selection test asks whether the unaided production route chooses the intended tool or skill on a realistic request. A recovery test asks whether it detects and handles a realistic failure. Use task-shaped prompts with both positive and negative opportunities. Include the incumbent route or strongest alternative where it could change the decision.

## Independent execution and judgment

Give one fresh native Luna executor only the scenario inputs, allowed effects, relevant candidate access, and case IDs. Batch explicit capability cases when doing so stays within the tool budget. Give a separate fresh Sol evaluator the rubric and observed output or artifacts, with candidate labels anonymized where practical. Do not supply the desired answer, the whole conversation, or the earlier selection rationale to either agent. The evaluator reports evidence for each rubric item, not a single impression of quality. Do not escalate to another review model as a default response to uncertainty; use the one planned follow-up when it can change the decision.

For unaided production-route tests, start a fresh context per case with the same effective configuration a user would receive. Do not mention the candidate skill in the test prompt unless explicit invocation is what the case tests. Repeat independent fresh-context cases only when the decision depends on reliability; report the denominator and observed variation. Use `record` to append bounded observations and `report` to store the evaluator's conclusion. Save each raw output or artifact once within the run and do not rewrite it after review. Keep the immutable raw evidence distinct from the Sol evaluator's summary. A record contains `caseId`, actual `model`, `status` (`success`, `failed`, `blocked`, or `skipped`), `toolCalls`, a concrete `observation`, and optional `artifacts` relative to its run folder. If no model executed, use `model: null` only with blocked or skipped status and zero tool calls. Include observed `usage` counters when available; leave them null rather than estimating them from text length. The report contains `model: "gpt-6-sol"` and `recommendations`, each with `candidateId`, `verdict` (`supported`, `conditional`, `inconclusive`, or `rejected`), recorded `caseIds`, and a reason.

## Interpretation

Classify each claim as supported, rejected, conditional, or inconclusive. State which observations establish the claim and which dependencies were unavailable. A passing explicit capability test does not establish automatic activation. One successful selection does not establish a universal routing guarantee. Failure to access a model, service, or account is a test limitation; do not substitute another model or silently score the candidate as a behavioral failure. Stop at the agreed budget and present remaining uncertainty instead of growing an open-ended test campaign.
