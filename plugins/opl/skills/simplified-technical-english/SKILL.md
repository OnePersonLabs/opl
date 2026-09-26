---
name: simplified-technical-english
description: Write or revise normative specifications, operational instructions, agent-consumed text, and implementation-guiding technical prose with Simplified Technical English principles. Use during other workflows that author such text; do not impose this register on human-facing explanatory or persuasive prose.
---

# Simplified Technical English for software work

Apply the clarity principles of ASD-STE100 to eligible software prose. This skill changes expression, not product intent. It does not supply missing product decisions or certify formal ASD-STE100 compliance.

## Route by purpose and reader

- **Normative or operational:** For requirements, acceptance criteria, procedures, and instructions another agent must act on, state one action or testable claim at a time. Put conditions before their effects. Name the actor when it matters. Reuse one term for each concept.
- **Implementation guidance:** For technical explanations that guide a design or implementation, use direct verbs and short, coherent paragraphs. Retain the vocabulary needed for precision; do not force a controlled dictionary.
- **Human-facing prose:** When the primary purpose is to explain, teach, or persuade a person, preserve the voice and structure suited to that reader. Do not apply a controlled register solely because the subject is technical.

Purpose outranks filename. If one artifact contains different kinds of text, apply the rules to the eligible sections rather than flattening the whole artifact.

## Preserve meaning

Read the source and its governing schema or instructions before rewriting. Keep all conditions, exceptions, numbers, units, references, defined terms, and the force of requirement words such as `MUST`, `SHOULD`, and `MAY`. When drafting from a sparse request, state only claims that follow from it. Do not add behavior, exceptions, guarantees, implementation constraints, error details, or ancillary test requirements merely to make a requirement sound more testable. Ask for a missing decision when it changes the required behavior. Keep domain terms when a plain substitute would change meaning; define an unfamiliar term when that helps the intended reader. Do not rewrite code, identifiers, command syntax, or quotations. When a shorter sentence would lose precision, keep the longer one.

For example, if the only source says, "Reject expired tokens without changing stored data," a complete requirement is: "If a token is expired, the service MUST reject the request and MUST NOT change stored data." Additional error formats, exceptions, and implementation steps need their own source.

## Review

After drafting an eligible Markdown artifact, run `python -B -X utf8 scripts/ste_lint.py --mode normative <path>` for normative or operational prose, or `--mode guidance` for implementation guidance. Use `python3` on POSIX. Run the script from this skill directory or pass its absolute path. It reports possible mechanical problems and never edits the artifact. Review each finding in context; fix it only when the change preserves meaning. For a mixed artifact, lint only eligible sections when they can be isolated; otherwise self-check those sections. For eligible prose not saved to a file, self-check sentence structure, terminology, and semantic preservation without creating a file only for linting.
