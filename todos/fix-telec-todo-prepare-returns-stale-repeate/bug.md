# Bug: telec todo prepare returns stale/repeated instructions when called from worktree path

## Symptom

telec todo prepare returns stale/repeated instructions when called from worktree path

## Detail

## Observed behavior

When the orchestrator calls `telec todo prepare web-tui-shell` after `telec todo mark-phase web-tui-shell --phase requirements --status complete` succeeds, the state machine returns the same DISCOVERY instruction again instead of advancing to the next phase (PLAN DRAFTING or REQUIREMENTS REVIEW).

The mark-phase command succeeds — it stamps `artifacts.requirements.produced_at` and updates the digest in state.yaml. But the subsequent `telec todo prepare` call returns the same instruction as before (dispatch discovery worker), as if the state hadn't changed.

Calling `telec todo prepare` again from the project root after some time passes returns the correct next instruction (PLAN DRAFTING).

## Reproduction sequence

1. `telec todo prepare web-tui-shell` → returns DISCOVERY instruction
2. Dispatch discovery worker, worker completes and writes requirements.md
3. `telec todo mark-phase web-tui-shell --phase requirements --status complete` → OK, artifact stamped
4. `telec todo prepare web-tui-shell` → **BUG: returns DISCOVERY instruction again** (current: input_assessment unchanged)
5. Wait, call again from project root → correctly returns PLAN DRAFTING instruction

## Suspected cause

Possible race condition or operation caching — the durable operation system may return a cached result from the previous prepare call instead of re-evaluating state. Or the state machine reads state.yaml before mark-phase has flushed to disk.

## Environment

- Slug: web-tui-shell
- state.yaml showed current: input_assessment throughout, even after artifact stamp
- mark-phase reported success both times
- requirements.md existed in both repo root and worktree todos/ directories

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-25

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
