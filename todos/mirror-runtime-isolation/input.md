# Input: mirror-runtime-isolation

## Problem

API responsiveness is still degraded even after `/todos/work` moved to receipts. The daemon still shares one runtime for API endpoints, background workers, and mirror reconciliation. Mirror reconciliation repeatedly processes a large fixed set and can starve the control plane.

## Current symptoms

- Slow API watch entries still occur for read endpoints (`/sessions`, `/health`, `/computers`) during starvation windows.
- `/todos/integrate` is still foreground and can stay in flight for long durations.
- Mirror reconciliation repeatedly processes thousands of transcripts per pass instead of converging.
- Discovery currently includes non-canonical sources (`codex .history`, `claude subagents`) that must not participate in the hot corpus.
- Current fallback identity behavior is lossy and causes collisions/overwrites.

## Decisions already made

- Mirrors may lag by minutes (eventual consistency is acceptable).
- `/todos/integrate` should become receipt-backed like `/todos/work`.
- Hot corpus must be an allowlist by agent, not a blacklist.
- `.history` and `subagents` are not part of mirror discovery/reconciliation/search.
- Mirror identity must come from canonical source identity, never fallback `session_id` semantics.
- DB split is conditional on measured post-prune write volume.

## Non-goals

- No broad search product redesign in this todo.
- No preservation of heuristic identity model.
- No bundling `/todos/integrate` receipt work into mirror surgery.
- No adding features for excluded transcript sources.

## Success shape

- Control-plane responsiveness stays stable while reconciliation runs.
- Reconciliation converges (processed rows trend to near zero in steady state).
- Empty transcripts are skipped durably and do not reprocess forever.
- Mirror key semantics are deterministic and collision-safe.
- DB isolation is applied when measurement gate indicates same-DB write pressure remains too high.
