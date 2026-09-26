# Skill Scoring Rubric

Load this reference only when the user requests a score, grade, comparison, or
quantitative readiness assessment.

## Rubric

Total: 120 points.

| Dimension | Max | Evaluate |
| --- | ---: | --- |
| Knowledge Delta | 20 | Does the skill add expert knowledge beyond what the active Codex model normally infers? |
| Mindset And Procedure | 15 | Does it transfer useful thinking patterns and domain-specific workflow rather than generic steps? |
| Anti-Patterns | 15 | Does it name specific failures and explain why they matter? |
| Description Quality | 15 | Does frontmatter state the trigger situations and useful discovery keywords? |
| Progressive Disclosure | 15 | Are references, scripts, and assets loaded only under explicit conditions? |
| Freedom Calibration | 15 | Is guidance strict where errors are costly and flexible where judgment matters? |
| Pattern Fit | 10 | Does the skill follow a coherent mindset, navigation, process, tool, or review pattern? |
| Practical Usability | 15 | Can Codex act without guessing missing state or inventing tools? |

## Evaluation Protocol

1. Apply the shared workflow in `SKILL.md` and the package review in
   `skill-packages.md`.
2. Classify each major body section:
   - **Expert**: non-obvious domain judgment or workflow.
   - **Activation**: a brief reminder that usefully changes behavior.
   - **Redundant**: generic advice the active model already knows.
3. Score every rubric dimension with file evidence.
4. Assign the grade:
   - A: 108-120
   - B: 96-107
   - C: 84-95
   - D: 72-83
   - F: below 72
5. Do not inflate scores for length or formatting. Penalize token waste, weak
   descriptions, unverified claims, and unavailable tools.

## Report Contract

```markdown
# Skill Evaluation Report: <skill>

## Summary

- Score: <n>/120
- Grade: <A-F>
- Pattern: <pattern>
- Knowledge Ratio: E:A:R = <n>:<n>:<n>
- Verdict: <one sentence>

## Dimension Scores

| Dimension | Score | Max | Evidence |
| --- | ---: | ---: | --- |

## Critical Issues

- [severity] [file:line] Problem -- consequence -- required fix

## Top Improvements

1. <highest-impact fix>
2. <next fix>
3. <next fix>

## Validation

<commands run and results, or commands not run and why>
```
