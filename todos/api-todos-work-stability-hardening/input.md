# Input: api-todos-work-stability-hardening

## Context

- API watchdog logged `HANG_DUMP reason=loop_lag_679.4ms` on 2026-02-26 while `/todos/work` traffic was active.
- Thread dump repeatedly showed `aiosqlite` worker threads and `asyncio._do_waitpid`.
- Operational symptom is request-path latency spikes and noisy hang diagnostics.

## Actionable vs low-signal

### Actionable

1. `/todos/work` calls `next_work(...)`.
2. `next_work(...)` calls `ensure_worktree(...)`.
3. `ensure_worktree(...)` currently runs `_prepare_worktree(...)` every time a worktree already exists.
4. `_prepare_worktree(...)` can run expensive subprocess work (`tools/worktree-prepare.sh`, `make install`, `pnpm install`/`npm install`).
5. `next_work(...)` also always performs `sync_main_to_worktree(...)` and `sync_slug_todo_from_main_to_worktree(...)`.
6. Build gates run in the same request path and can add additional synchronous cost.

### Low-signal (symptom, not root cause)

- `aiosqlite/core.py:_connection_worker_thread` frames are expected background DB workers.
- `asyncio/unix_events.py:_do_waitpid` frames are expected subprocess wait helpers.
- The hang dump snapshot does not by itself identify which next_work phase consumed time.

## Problem statement

`/todos/work` currently combines orchestration with expensive prep/sync/gate operations in a synchronous API call. Repeated calls can re-run idempotent but costly work, creating long inflight requests and loop-lag watchdog alerts.

## Objective

Preserve current safety guarantees while making repeated `/todos/work` calls predictable and materially faster.

## Candidate changes (full list)

- Add per-phase timing instrumentation inside `next_work(...)`.
- Add slug-scoped single-flight for worktree preparation.
- Change preparation policy from "always run" to "run when needed" (new worktree, drift signal, explicit refresh).
- Add conditional sync policy so main/todo sync only runs when refs/content changed.
- Keep build gates functionally identical, but record timing and failure mode clearly.
- Optional follow-up: move heavyweight checks out of request path if latency still exceeds targets.
- Optional follow-up: tune watchdog thresholds only after phase timings are available.

## First-pass exclusions

- No blanket watchdog threshold increase before phase-level evidence.
- No database-layer rewrite or aiosqlite replacement.
- No host-level service/launch configuration changes.
- No broad next-machine architecture rewrite.

## Acceptance signals

- Repeated `/todos/work` calls on unchanged, prepared worktrees do not rerun prep each time.
- Logs show per-phase timings with slug/path correlation.
- `/todos/work`-correlated hang dumps drop materially after rollout.
- Drift recovery still works when preparation is genuinely needed.
