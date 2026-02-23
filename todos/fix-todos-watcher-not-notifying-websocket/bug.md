# Bug: TUI PreparationView Not Refreshing on todo WebSocket Events

## Symptom

When todo files change (state.yaml modifications), the TUI's PreparationView does not refresh with updated todo data despite receiving WebSocket notifications. The todo list shows stale data until manual reload.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-23

## Investigation

Traced the full chain from filesystem to TUI display:

1. **TodoWatcher** (todo_watcher.py) detects file changes via watchdog, debounces, calls `cache.refresh_local_todos()`.
2. **Cache** re-reads todos via `assemble_roadmap()`, stores `list[TodoInfo]` with full shape (after, group, files, status, dor_score, etc.), emits cache notification.
3. **ApiServer** `_on_cache_change` receives notification, builds `RefreshEventDTO`, broadcasts via WebSocket after 0.25s debounce.
4. **TUI** `_handle_ws_event` receives `RefreshEvent`, falls to else clause, calls `_refresh_data()`.
5. **`_refresh_data()`** fetches fresh data from HTTP API, calls `PreparationView.update_data()`.

Steps 1-5 all work correctly. The WebSocket chain delivers fresh data to the view.

The bug is in step 6: `PreparationView.update_data()` only calls `_rebuild()` when the **slug set** changes (todo added or removed). For state.yaml edits (DOR score, build status, review status, phase transitions), the slug set stays identical so `_rebuild()` is never called and the display stays stale.

## Root Cause

`PreparationView.update_data()` in `teleclaude/cli/tui/views/preparation.py` compared only `{t.slug for ...}` old vs new. Any change that doesn't add/remove a slug (e.g., editing state.yaml to update DOR score, build status, phase, findings) was invisible to the change detection.

## Fix Applied

Replaced the slug-set comparison with a full data fingerprint that includes all display-relevant fields: slug, status, dor_score, build_status, review_status, deferrals_status, findings_count, files, after, and group. The view now rebuilds whenever any todo property changes, not just when todos are added or removed.
