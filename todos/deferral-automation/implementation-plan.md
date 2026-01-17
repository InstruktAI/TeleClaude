# Implementation Plan: Deferral Automation

## Phase 0: Builder Deferral Contract (first)

1. Update `~/.agents/commands/next-build.md`:
   - Define strict criteria for when a deferral is permitted.
   - Provide a precise deferrals.md schema (fields).
2. Ensure `next-build` instructions explicitly forbid casual deferrals.

## Phase 1: State Machine Integration (second)

1. Update `teleclaude/core/next_machine.py` to detect existence of `deferrals.md` AND `NOT state.json.deferrals_processed` and output:
   - If true: ensure review runs first; schedule `next-defer` after review completion.
2. Make the orchestration output explicit (no narrative).

## Phase 2: Deferral Resolution Automation

1. Add `next-defer` command:
   - Read `~/.agents/commands/prime-administrator.md` first.
   - Read deferrals.md.
   - For each entry, apply rule:
      - `Suggested outcome: NEW_TODO` → create new todo (input.md prefilled from deferral).
      - `Suggested outcome: NOOP` → do nothing.
   - Set `state.json.deferrals_processed = true`.
   - Assess whether to add a dependency from new todo to current slug.
2. Ensure deferrals.md uses the defined schema fields.

## Phase 3: Primer Cleanup

1. Remove the deferral handling block from `~/.agents/commands/prime-orchestrator.md`.
2. Keep the orchestrator primer focused on execution-only behavior.

## Phase 4: Commit & Distribute (agents repo)

1. Commit changes in `~/.agents` (commands) with a clear message.
2. Deploy per `~/.agents/README.md`.

## Phase 5: Verification

1. Add tests or scripted checks to ensure:
   - Orchestrator scripts surface deferral resolution steps.
2. Verify prime-orchestrator is free of deferral logic.

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
