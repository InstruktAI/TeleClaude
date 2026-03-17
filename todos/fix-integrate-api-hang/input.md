# fix-integrate-api-hang — Input

# API Hang: /todos/integrate endpoint blocks thread pool

## Problem

The `/todos/integrate` REST endpoint is the only lifecycle endpoint that runs inline — it `await`s `next_integrate()` directly in the request handler (todo_routes.py:140), while `/todos/work` correctly uses the operations service for receipt-based 202 responses.

## Root Cause Chain

`next_integrate` uses `asyncio.to_thread()` (state_machine.py:278), so it doesn't block the event loop directly. But it causes **thread pool exhaustion**:

1. **`_dispatch_sync`** runs a loop of up to 50 iterations, each calling synchronous `subprocess.run` for git commands (`_run_git` with 30s timeout). A single integrate call can hold a thread for minutes.

2. **`_scan_finalize_ready_candidates`** (step_functions.py:385) iterates over every worktree directory and runs **two** git subprocess calls per candidate (`ls-remote` + `merge-base`). With N worktrees, that's 2N blocking subprocess calls, each with a 30s timeout.

3. **`git ls-remote origin`** (step_functions.py:301) is a **network call** — it contacts the remote. If the remote is slow or the network hiccups, this blocks the thread for up to 30 seconds per candidate.

4. **`git pull --ff-only origin main`** (state_machine.py:89) runs on every entry — another network-blocking subprocess.

5. The default `ThreadPoolExecutor` has `min(32, os.cpu_count() + 4)` workers (~14 on M-series Mac). The hang dump shows 6 threads all stuck in `concurrent.futures.thread._worker`, starving other `to_thread` calls across the entire API server.

## Failure Chain

```
Agent calls POST /todos/integrate
  → todo_integrate() awaits next_integrate()
    → asyncio.to_thread(_dispatch_sync)
      → _dispatch_sync grabs a thread pool worker
        → git pull --ff-only origin main (network, up to 30s)
        → _scan_finalize_ready_candidates:
            → for each worktree:
                → git ls-remote origin (network, up to 30s each)
                → git merge-base (local, fast)
        → _step loop: more git subprocesses per phase
      → thread held for potentially minutes
```

## Evidence

Stack trace from API HANG_DUMP (2026-03-17T18:21:10.569Z):
- Thread blocked in `step_functions.py:56 _run_git` → `subprocess.run` → `selectors.select`
- Called from `step_functions.py:301 _scan_finalize_ready_candidates`
- Called from `step_functions.py:385 _step_idle`

## Fix

The integrate endpoint needs the same receipt-based treatment as `/todos/work`:
- Return 202 with an operation ID immediately
- Run the state machine in a durable operation (via `OperationsService.submit_todo_integrate` or similar)
- Callers poll the operation status

### Key files
- `teleclaude/api/todo_routes.py` — endpoint definition (lines 120-144)
- `teleclaude/core/integration/state_machine.py` — `next_integrate` entry point
- `teleclaude/core/integration/step_functions.py` — `_run_git`, `_scan_finalize_ready_candidates`
- `teleclaude/core/operations/service.py` — existing receipt-based pattern (reference: `submit_todo_work`)
