---
name: recover-request-user-input
description: Recover immediately when the native `request_user_input` tool returns the exact failure `request_user_input is unavailable in Default mode`. Invoke this skill for that observed tool-result scenario even when the user did not name a skill; do not invoke it for successful questions or unrelated tool errors.
---

# Recover unavailable request input

Do not retry immediately or replace the structured question with a prose
questionnaire. Respond with one compact paragraph:

> `request_user_input` isn't available in Default mode. Switch to Plan Mode and
> reply `retry`, reply `enable` to enable it for future sessions and create a
> handoff, or ask for something else.

If the user replies `retry`, attempt the original native question again. If it
fails, repeat the same compact paragraph.

If the user replies `enable`, that reply authorizes only
`codex features enable default_mode_request_user_input`, verification with
`codex features list`, and invocation of `$opl:handoff`. Preserve the
originating task, settled decisions, remaining questions, and recommendations
in the handoff. If a named skill initiated the failed call, instruct the next
agent to invoke that same fully qualified skill as its first action and list it
under suggested skills.

Enabling the feature cannot retrofit the current session. The handoff prepares
continuity but does not create, open, or start a session. The user must manually
create and start the new Codex session from the generated handoff document.

If the user accepts the failure or asks for something else, end the originating
workflow without changing configuration or generating a handoff, then handle
the new request normally. Do not repeat this recovery unless another
`request_user_input` call fails.
