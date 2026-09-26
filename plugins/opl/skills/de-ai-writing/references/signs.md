# Signs of AI writing: catalogue and fixes

This is an adaptation for general human-facing prose of Wikipedia's [Signs of AI writing](https://en.wikipedia.org/w/index.php?title=Wikipedia:Signs_of_AI_writing&oldid=1376434705), retrieved 2026-09-25.

- Source revision: `1376434705`
- Source timestamp: `2026-09-24T03:34:26Z`
- Last reviewed: `2026-09-25`
- License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- Scope: Wikipedia-only markup, citation, category, edit-summary, and moderation signs are omitted.

The source is a field guide, not an authorship test. These patterns are symptoms. Fix what a sentence is doing: padding, exaggerating, hedging, restating, or correcting a misconception nobody raised. Do not swap one conspicuous word for a synonym while preserving the same empty sentence.

`Scanner` below states whether `scripts/check_ai_signs.py` can find part of the sign. Scanner matches require editorial review.

## Content

### 1.1 Undue significance or legacy

Ordinary facts receive an unsupported statement about broader trends, a pivotal role, an enduring legacy, or why the fact matters.

Typical language includes `stands as`, `a testament to`, `pivotal role`, `underscores its importance`, `reflects broader`, `enduring legacy`, `setting the stage for`, `turning point`, and abstract uses of `landscape`.

Delete the significance claim or replace it with the specific fact that demonstrates it.

Scanner: phrase matches.

### 1.2 Canned notability

The prose tries to establish importance by listing coverage or describing the source rather than stating what happened. Typical language includes `independent coverage`, `leading expert`, `featured in`, and `active social media presence`.

Use coverage only to support a concrete claim.

Scanner: phrase matches.

### 1.3 Superficial analysis

A factual sentence ends with an `-ing` clause that interprets the fact without adding evidence: `highlighting`, `underscoring`, `reflecting`, `showcasing`, or `ensuring`.

Cut the clause. If the interpretation matters, give it evidence in its own sentence.

Scanner: common comma-plus-participle forms.

### 1.4 Promotional language

Neutral material reads like a press release or travel listing. Common tells include `vibrant`, `rich heritage`, `nestled`, `in the heart of`, `breathtaking`, `world-class`, `state-of-the-art`, `seamless`, `groundbreaking`, and `diverse array`.

Replace praise with the fact that earns it, or remove it.

Scanner: phrase matches.

### 1.5 Vague attribution

An opinion is assigned to unnamed authorities: `experts argue`, `observers note`, `studies show`, `industry reports`, or `widely regarded`.

Name the source, own the judgment, or remove it.

Scanner: phrase matches.

### 1.6 Formulaic challenges and prospects

A section follows `Despite its strengths, X faces challenges` with an optimistic `Despite these challenges` conclusion.

Put each real problem where it belongs and remove the automatic recovery ending.

Scanner: common formula phrases.

### 1.7 Title-defining lead

A lead begins with `X refers to` or describes a list as a `curated compilation` instead of starting with the subject.

Define the subject directly.

Scanner: common lead forms.

### 1.8 Completeness-shaped headings

Headings such as `Awards and recognition` or generic `X and Y` pairings can create sections that exist to complete an outline rather than serve the reader.

Keep the heading only when the material needs a separate section.

Scanner: judgment only.

## Language and grammar

### 2.1 Dense AI-associated vocabulary

One ordinary use proves nothing. A cluster is the signal. Common words and phrases include `additionally`, `crucial`, `delve`, `enhance`, `foster`, `garner`, `intricate`, `interplay`, `meticulous`, `pivotal`, `robust`, `showcase`, `tapestry`, `testament`, `underscore`, `valuable insights`, and abstract `landscape`.

Use the ordinary word or remove the padding. Explain why something matters instead of replacing `crucial` with another intensifier.

Scanner: reports a sentence or line containing three or more distinct listed terms.

### 2.2 Avoiding `is`, `are`, and `has`

Plain verbs become `serves as`, `stands as`, `functions as`, `operates as`, `represents`, `boasts`, `features`, `maintains`, or `offers`.

Use `is`, `are`, or `has` when that is the meaning.

Scanner: phrase matches.

### 2.3 Vague association

Phrases such as `associated with`, `in connection with`, or `connected to` hide a known relationship.

Name the relationship.

Scanner: phrase matches.

### 2.4 Negative parallelism

The prose corrects a misconception the reader did not have: `not only ... but also`, `not just X, but Y`, `this isn't X, it's Y`, or `no X, no Y, just Z`.

State the positive claim. Keep a contrast when the reader would reasonably assume the opposite.

Scanner: common constructions.

### 2.5 Rule of three

Triplets of adjectives or short imperatives can substitute rhythm for information. Keep a three-item list when it is a real list of facts. Otherwise retain the item that matters and vary the rhythm.

Scanner: judgment only because ordinary three-item lists are common.

### 2.6 Elegant variation

Older models often cycled through synonyms to avoid repeating a noun. Current Wikipedia guidance treats this as a historical indicator rather than a reliable general sign.

Repeat the plain noun or use a pronoun when synonym cycling calls attention to itself. Do not rewrite ordinary lexical variety.

Scanner: judgment only.

## Style and formatting

### 3.1 Title-style headings

Use sentence case unless the house style requires title case. A document title can follow its own convention.

Scanner: Markdown headings in title case.

### 3.2 Excess boldface

Do not bold scattered key phrases merely to manufacture takeaways. Bold a term at its definition or where the format genuinely requires emphasis.

Scanner: lines containing three or more bold spans.

### 3.3 Inline-header lists

Bullets shaped as `**Label:** explanation` often fragment prose without adding structure.

Use prose, an ordinary list, or a real table when the information is tabular.

Scanner: Markdown list pattern.

### 3.4 Em-dash overuse

Repeated em dashes can give every qualification the same dramatic rhythm. Rewrite with commas, colons, parentheses, or full stops. Do not replace the mark mechanically with another dash. An occasional em dash can be right.

Scanner: spaced em dashes and paired em dashes on one line.

### 3.5 Emoji as structure

Emoji attached to headings and bullets usually add decoration rather than meaning.

Remove them unless the medium or house style calls for them.

Scanner: heading or bullet prefixes.

### 3.6 Unnecessary small tables

A two-row table can make a simple comparison harder to read. Use a sentence or list unless the values are genuinely tabular.

Scanner: judgment only.

### 3.7 Mixed quotation conventions

Match the surrounding straight or curly quotation style. Curly quotation marks alone are not evidence of AI writing.

Scanner: not scanned.

### 3.8 Repeated thematic breaks

Rules between every section create mechanical segmentation. Keep them only when the format needs a real break.

Scanner: repeated Markdown thematic breaks, excluding frontmatter.

## Chat residue

### 4.1 Collaborative leftovers

Remove `Certainly`, `Great question`, `I hope this helps`, `let me know if`, `would you like me to`, and `in this section, we will discuss` when they have leaked into the deliverable.

Scanner: phrase matches.

### 4.2 Knowledge-cutoff disclaimers and padded unknowns

Remove `as of my last update`, `based on available information`, `not widely documented`, and speculation about what missing information probably means.

If a fact is unknown, say so once and tell the reader what to do: `Opening hours are not posted; call ahead.`

Scanner: phrase matches.

### 4.3 Placeholders

Fill in or remove `[Your Name]`, `INSERT_URL`, `2025-XX-XX`, and similar template residue.

Scanner: common placeholder forms.

## Historical habits

### 5.1 Didactic disclaimers

Replace `it is important to note`, `it is worth noting`, `keep in mind`, and generic `may vary` with the actual information.

Scanner: phrase matches.

### 5.2 Summary endings

Avoid `In summary`, `In conclusion`, `Overall`, or `Ultimately` when the final paragraph merely repeats the piece. End on the last new fact.

Scanner: paragraph-opening phrases. Whether the paragraph is redundant remains a judgment.

## Prefer these human patterns

- Plain `is` and `has` sentences.
- Ordinary verbs: `wrote`, `moved`, `used`, `tried`, `died`, and `to`.
- Definite claims when the evidence supports them.
- Specific or unusual facts instead of generic praise.
- Natural variation in sentence length and rhythm.
- Honest uncertainty stated once and concretely.

## Do not "fix" these

Perfect grammar, a mixed casual and formal register, formal prose, a long word, one transition, an unsupported claim, or correct formatting is not by itself a useful sign. Never rewrite a real quotation, title, source text, legal text, code, identifier, or command to remove a pattern.
