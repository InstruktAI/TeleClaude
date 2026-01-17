# Requirements: Deferral Automation

## Goal

Deferrals are automated and deterministic. Orchestrator executes `next_machine` output only.

## Functional Requirements

1. **Next-build generates deferrals (first priority)**

   - `next-build` creates deferrals.
   - Deferrals are for truly out-of-scope work or missing decisions.

2. **Next-machine emits a single pointer**

   - Detects `deferrals.md`.
   - Emits a single deterministic instruction: “run `next-defer` for this slug.”

3. **New command: next-defer (stateless executor)**

   - Runs in isolation.
   - Reads `deferrals.md`.
   - Outputs either a new todo from deferrals or no-op.
   - When creating a new todo, assess whether a dependency on the current todo slug is appropriate.

4. **New command: prime-administrator**

   - Centralizes process-management guidance.
   - Keeps orchestration and process management distinct roles.

5. **Orchestrator stays thin**

   - No deferral decision tree in `prime-orchestrator.md`.
   - Executes deterministic scripts from `next_machine` only.

6. **Deferrals format and location**

   - Location: `todos/{slug}/deferrals.md`.
   - Each deferral entry includes: description, reason, required decision, and suggested path.
   - **Schema (exact):**
     - `Title:` short summary
     - `Why deferred:` reason
     - `Decision needed:` what is required to proceed
     - `Suggested outcome:` `NEW_TODO` or `NOOP` (set by builder)
     - `Notes:` optional
   - **Example entry (valid deferral):**
     - Title: Queue migration strategy for existing outbox pipeline
     - Why deferred: Replacing the current outbox changes core delivery semantics and retry behavior.
     - Decision needed: Confirm whether to replace or extend the existing pipeline and define migration constraints.
     - Suggested outcome: NEW_TODO
     - Notes: Architectural change to existing system.

7. **Automated detection**

   - `next_machine` detects presence of `deferrals.md`.
   - `next_machine` checks `state.json.deferrals_processed` to avoid repeat surfacing.
   - If deferrals exist and not processed: schedule `next-defer` only after review completes.

8. **Automation-assisted resolution**
   - `next-defer` reads `deferrals.md`, creates a new todo or no-ops, then sets `state.json.deferrals_processed = true`.
   - `state.json.deferrals_processed` lives in `todos/{slug}/state.json` (worktree).
   - If a new deferrals.md is created later, reset `deferrals_processed` to false.
   - Review runs before `next-defer` so deferrals are validated input.

## Non-Goals

- No manual deferral resolution process in the orchestrator primer.
- No free-form deferrals without the required schema.

## Success Criteria

- Orchestrator prompt is clean: no deferral procedure block.
- Deferrals are created only by builders and are surfaced deterministically by `next_machine`.
- Follow-up todos can be spawned reliably from deferral entries.
