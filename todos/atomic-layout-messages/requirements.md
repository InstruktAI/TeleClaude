# atomic-layout-messages — Requirements

## Problem

A single TOGGLE_STICKY user action posts two separate Textual messages
(StickyChanged + PreviewChanged) into the message pump. The bridge's
`call_later` flush can fire between them due to asyncio pump interleaving,
producing a layout render with stale state — the sticky change is applied
but the preview change has not yet arrived.

## Success criteria

1. A user action that changes both sticky and preview state results in **at
   most one layout render**, and that render reflects the **final** combined
   state.
2. The bridge processes sticky and preview mutations atomically — no
   intermediate layout flush occurs between them.
3. Existing `StickyChanged` and `PreviewChanged` messages continue to work
   for call sites that modify only one concern (stale-session pruning,
   single preview change, focus-pane, etc.).

## Requirements

### R1 — Atomic layout state notification

When a user action changes both sticky session list and preview session in
the same logical operation, the system must deliver a single notification
carrying both values to the bridge. The bridge must apply both before
marking layout dirty.

**Verification:** a test asserts that the TOGGLE_STICKY path produces
exactly one layout-triggering message (not two separate ones) and that the
bridge state after processing reflects both the sticky and preview changes.

### R2 — Pure state mutation for toggle-sticky

The sticky-toggle logic that mutates `_sticky_session_ids`, updates
`SessionRow.is_sticky` flags, and clears highlights must be extractable as
a side-effect-free-of-messages operation. Message posting happens after the
combined state is ready.

**Verification:** the extracted mutation can be called without any message
being posted; existing toggle-sticky tests continue to pass. [inferred]

### R3 — All dual-change call sites updated

Every call site that currently posts both `StickyChanged` and
`PreviewChanged` for a single user action must use the atomic notification
instead. At minimum this includes:

- The TOGGLE_STICKY keyboard handler (Space double-press path with
  `clear_preview`).
- The double-click handler in the sessions click handler. [inferred]
- The batch-toggle action (`action_toggle_sticky_sessions`) when it clears
  preview as part of scope-toggle-off. [inferred]

**Verification:** grep for paired `StickyChanged`/`PreviewChanged` posts
within the same handler block; none should remain for single-user-action
flows.

### R4 — App-level forwarding

The app must forward the atomic notification to the bridge following the
same pattern as existing message forwarding (banner compactness update +
sky-width invalidation). [inferred]

**Verification:** the app handler delegates to the bridge handler,
updates banner compactness, and schedules sky-width invalidation.

### R5 — Backward compatibility

`StickyChanged` and `PreviewChanged` remain as independent messages.
Call sites that change only sticky or only preview state are not modified.

**Verification:** existing tests for individual `StickyChanged` and
`PreviewChanged` handling continue to pass without modification.

## Scope

~6 files, ~40 lines of change. Single atomic behavior — one session, no
split needed. The change is contained within the TUI messaging and bridge
layer.

## Out of scope

- Refactoring the bridge's `call_later` batching mechanism.
- Changing the controller/reducer architecture (state.py).
- Modifying pane layout rendering logic.
