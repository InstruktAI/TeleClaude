# Implementation Plan: Deferral Automation

## Phase 0: Builder Deferral Contract (first)

- [x] Update `~/.agents/commands/next-build.md`:
   - Define strict criteria for when a deferral is permitted.
   - Provide a precise deferrals.md schema (fields).
- [x] Ensure `next-build` instructions explicitly forbid casual deferrals.

## Phase 1: State Machine Integration (second)

- [x] Update `teleclaude/core/next_machine.py` to detect existence of `deferrals.md` AND `NOT state.json.deferrals_processed` and output:
   - If true: ensure review runs first; schedule `next-defer` after review completion.
- [x] Make the orchestration output explicit (no narrative).

## Phase 2: Deferral Resolution Automation

- [x] Add `next-defer` command (create `~/.agents/commands/next-defer.md`):
   - Read `~/.agents/commands/prime-administrator.md` first.
   - Read deferrals.md.
   - For each entry, apply rule:
      - `Suggested outcome: NEW_TODO` → create new todo (input.md prefilled from deferral).
      - `Suggested outcome: NOOP` → do nothing.
   - Set `state.json.deferrals_processed = true`.
   - Assess whether to add a dependency from new todo to current slug.
- [x] Ensure `prime-administrator.md` is set up correctly (Create/Update `~/.agents/commands/prime-administrator.md`).
- [x] Ensure deferrals.md uses the defined schema fields.

## Phase 3: Primer Cleanup

- [ ] Remove the deferral handling block from `~/.agents/commands/prime-orchestrator.md`.
- [ ] Keep the orchestrator primer focused on execution-only behavior.

## Phase 4: Commit & Distribute (agents repo)

- [ ] Commit changes in `~/.agents` (commands) with a clear message.
- [ ] Deploy per `~/.agents/README.md`.

## Phase 5: Verification

- [ ] Add tests or scripted checks to ensure:
   - Orchestrator scripts surface deferral resolution steps.
- [ ] Verify prime-orchestrator is free of deferral logic.

## Definition of Done

- next-build writes deferrals.md in the specified schema.
- next-machine emits only a single pointer to next-defer when deferrals exist and not processed.
- next-defer creates a new todo (or no-op) based on deferrals.
- next-defer sets `state.json.deferrals_processed = true`.
- prime-orchestrator contains no deferral logic.
- agents repo changes committed and deployed per ~/.agents/README.md.

## Deliverables

- Cleaned `prime-orchestrator.md`
- Updated `next-build.md` deferral rules + schema
- `next_machine` deterministic deferral gating
- Optional helper for generating follow-up todo input from deferrals