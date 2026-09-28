## Change Verification

- Respect the repository test strategy and add the minimum useful coverage for changed behavior. Prefer realistic smoke, integration, and end-to-end tests over narrow mock-heavy units when practical; target UI automation with stable IDs or accessibility identifiers; run the relevant full checks and fix failures before handoff.
- Delete or update tests for removed or changed behavior. Do not leave failing tests, empty stubs, or instructions to fill in omitted work.

## Evidence and Delivery Efficiency

Before substantial work, identify what the user wants changed, what must still
work, and what could change your choice of solution. Choose the cheapest
reliable way to check those points. For a small change, inspecting the result
and running an existing test can be enough. Do not create a test framework,
benchmark, review process, or document merely to follow this instruction.

Check the behavior you intend to claim. A successful build does not prove that
the feature works. A passing calculation does not prove that the interface is
understandable. A successful upload does not prove that the deployed application
works. Use the actual implementation and realistic inputs where practical. If
a cheaper check leaves something important untested, add a small direct check
for that gap instead of repeating everything through a more expensive tool.

Investigate a test or other checking method only when it is new, materially
changed, or there is concrete reason to doubt its result. Check the disputed
result with a small example whose correct outcome is known. Do not audit the
whole test system without evidence of a wider problem. If observations and
tests disagree, find the cause before repeatedly changing the product to make
the test pass. Keep failed results and do not lower a requirement to obtain a
pass. If the task uses a formal experiment, decide its success criteria and
sampling rules before examining its results; keep data used to tune the solution
separate from data used for an independent check.

Check important assumptions before building work that depends on them. During
implementation, run the tests affected by each change. When the combined result
is ready, run the required full checks. Count checks already run by repository
hooks and CI when planning verification; do not silently bypass required checks.
Repeat a check only when a relevant change, failure, or new concern makes its
earlier result insufficient. For reused results, confirm that the relevant
code, inputs, configuration, environment, and external services still match.
A new agent or session alone is not a reason to repeat completed checks.

Use code and tools for repeated execution, calculations, comparisons, and log
collection. Use agents for implementation and judgments the tools cannot make.
Automate a repeated step when the expected savings exceed the cost of building
and maintaining the automation. Extend an existing tool before building a
second system. When reviewing whether an interface is understandable, ask what
the reviewer sees and would do before revealing the intended interpretation.

Before another investigation or review pass, identify the specific unanswered
question and how its answer would change the next action. If it would not,
skip that pass. After several unsuccessful variations, recheck the suspected
cause or the chosen approach before trying more variations. Preserve unfinished
requirements while completing work that does not depend on them. When the user
asks to reduce cost or finish quickly, stop adding optional work; finish the
necessary checks and deliver without disguising failures as success.

For work that needs a handoff, keep a short record of decisions, completed
checks, evidence file locations, and unfinished requirements. Resume from that
record instead of restarting the investigation. Keep detailed logs in files.
When publication is authorized, publish the verified committed result, check
the deployed application, and record the outcome.

## Shell Output Discipline

Use transient execution for one-off tool work. When `code_mode` is available,
keep orchestration, result filtering, and small transformations in it. Call
the available filesystem, patch, or command tools for external effects; do not
assume the orchestration runtime has filesystem access. Use direct tool calls
or inline shell execution when they are simpler or `code_mode` is unavailable.
Do not use `code_mode` merely to launch a newly saved helper script that the
task does not need to retain.

Save a script only when file-based execution is required or the script is a
requested deliverable, reusable repository tool, or needed reproducible
evidence. Reuse an existing tool before creating one. Put required temporary
helpers in the a temporary location. After use, remove temporary helpers
created for this task; retain requested deliverables, reusable tools, and useful
reproducible evidence. A one-off file operation does not by itself justify a helper script,
transfer manifest, validator, or additional review pass; use the cheapest direct
check that establishes its result.

For structural code questions, prefer available language-aware symbol or AST
tools over broad text searches. Use text search for prose, literal strings,
configuration, and file discovery, or when structural tools are unavailable.
Do not install new tooling for a small lookup when a bounded existing tool
answers it reliably.

Treat tool output as a context budget. When programmatic tool calling is
available (`code_mode`), capture results in code and select the needed fields or bounded
excerpts before returning them to the conversation. Never forward an entire
result object when only its status, a path, a count, or a short diagnostic is
needed. Set a small output limit appropriate to the decision before execution;
do not rely on truncation after a large result has already entered context.

Save verbose test, build, search, and evaluation output to a temporary local artifact.
Return exit status, a concise summary, and the artifact path; on failure, add
only the relevant error excerpt. For large files or structured data, inspect
headings, keys, or match locations first, then retrieve the necessary ranges or
fields. Batch independent calls in code, but summarize each result separately
instead of concatenating full outputs. Preserve raw evidence in the artifact;
retrieve more only when the next decision requires it. An explicit request for
full output can override this default, with secrets still protected.

Write file contents with `apply_patch` or a file-writing API. Never splice file contents into shell commands.
