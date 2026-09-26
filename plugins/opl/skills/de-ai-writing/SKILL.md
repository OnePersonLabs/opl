---
name: de-ai-writing
description: Generate or revise human-facing prose to remove common signs of AI writing based on Wikipedia's Signs of AI writing. Use by default for explanatory, persuasive, editorial, marketing, social, email, and other prose written primarily for people; use $simplified-technical-english for normative, operational, agent-consumed, or implementation-guiding prose.
---

# De-AI writing

Write like a knowledgeable person with something specific to say. Prefer concrete facts, ordinary verbs, varied rhythm, and the voice appropriate to the reader. Remove generic significance, promotional padding, canned contrasts, vague attribution, and chatbot residue instead of replacing flagged words with synonyms.

Last source review: `2026-09-25`. On the first use 30 or more days after that date, read [references/maintenance.md](references/maintenance.md) and complete its due-check workflow before drafting. Do not make a source request before the interval expires.

## Choose the mode

- **Draft:** Apply the principles above without loading the catalogue or running a script. Preserve the requested voice, format, spelling convention, and length.
- **Rewrite or audit:** Read [references/signs.md](references/signs.md) before reviewing the text. If local text files are available, run `scripts/check_ai_signs.py` for a baseline and again after the rewrite.
- **Refresh this skill:** Read [references/maintenance.md](references/maintenance.md). Use that workflow when the 30-day source check is due or when the user explicitly asks to update the catalogue, scanner, or source status.

Purpose and reader determine the mode. Technical subject matter can still be human-facing prose. Normative requirements, operational procedures, agent instructions, and implementation guidance belong to `$simplified-technical-english`.

## Preserve the source

Keep every fact, number, name, date, link, claim, condition, and meaningful qualification. Keep quotations, titles, legal text, code, identifiers, and commands unchanged. Do not invent a vivid detail to replace vague prose. If a sentence contains only padding, delete it; if it contains information, retain that information in plain language.

Keep the author's person, tone, spelling, formatting system, and genuine quirks. A clean sentence does not need a rewrite merely because it is grammatical or formal.

## File review

Run the scanner with the active platform's Python interpreter:

```powershell
python -B -X utf8 scripts/check_ai_signs.py <path> [<path> ...]
python -B -X utf8 scripts/check_ai_signs.py <path> --summary
```

Use `python3` on POSIX. Paths can name supported files or directories. `-` reads plain text from standard input. The scanner is advisory: it finds mechanical signals, not authorship, and it cannot judge generic structure, unnecessary summaries, synonym cycling, or whether a contrast is warranted.

After editing, read the whole piece once for those judgment-dependent signs. A scanner hit can remain when it is quoted, literal, required by house style, or the clearest wording.

## Delivery

Lead with the finished prose or the edited files. For a review, add only the before and after counts, a few representative changes, and any deliberate remaining hits. Do not turn the report into another essay.
