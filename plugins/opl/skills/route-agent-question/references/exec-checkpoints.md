# Exec checkpoints

Exec is noninteractive. Use this route only for an already-authorized assignment
whose installed runtime and caller can preserve and resume its exact session.
Inspect local initial/resume help and effective configuration. Do not change
persistence, privacy, permissions, installation, or model presets to enable it.

1. Before launch, establish the caller's result contract and decision route.
   Preserve its output schema, required artifacts, and exit-status semantics.
   The child finishes safe independent work, withholds the dependent action,
   and returns a distinguishable BLOCKED result with the question and checkpoint.
   Do not call `request_user_input` in exec or keep stdin open for an answer loop.
2. Capture the launched session ID from authoritative runtime output. With
   `--json`, the installed CLI emits `thread.started` with `thread_id`. Verify
   that it identifies the launched session, not an attached child. Wait for
   normal process exit and account for writer processes. Assistant text and a
   completed model turn do not establish process exit or release ownership.
3. The caller decides or relays under the parent-routing authority rules. Keep
   the question, revision, return route, completed effects, and decision source
   in the existing assignment record.
4. Resume only that recorded session, once the prior writers have stopped.
   Never use `--last`, guess an ID, resume an unrelated user session, or start
   concurrent resumes. Verify cwd, workspace, Codex home, persistence, role and
   instructions, sandbox, approval policy, model, and effort. Set model and
   effort explicitly. Use safe argument arrays and a prompt file or closed
   stdin. If resume help provides no `--cd`, preserve the verified process cwd
   and check the resumed context instead of assuming inheritance.
5. Supply the scoped answer, validity context, and validated checkpoint. If
   resumed history lacks prior callback results, include their verified evidence
   from the existing record. Check consumption and repeated side effects in
   subsequent results. If exact continuation or its context
   cannot be verified, retain BLOCKED state and explain the limitation. A fresh
   writer requires the existing ownership and authorization procedure.

Treat arbitrary stdout as task data. Use authoritative runtime events and the
validated result contract for session identity and checkpoint handling. Keep
decision-dependent commands attached under Long Commands and Token Use.
