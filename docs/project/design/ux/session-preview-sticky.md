---
id: 'project/design/ux/session-preview-sticky'
type: 'design'
scope: 'project'
description: 'Preview and sticky session interaction model for TUI pane management.'
---

# Session Preview & Sticky — Design

## Required reads

- @docs/project/design/architecture/tui-state-layout.md
- @docs/project/design/architecture/tmux-management.md

## Purpose

Define the user-facing interaction model for previewing and pinning sessions in the TUI. The session list supports two pane visibility modes — preview (ephemeral, one at a time) and sticky (persistent, up to N) — that determine which tmux panes are visible alongside the TUI. This document specifies what happens for every combination of user action and session state so that behavior is deterministic and intuitive.

## Concepts

**Preview**: A temporary pane shown alongside the TUI. Only one preview can exist at a time. Navigating to a different session replaces the preview. The preview is the weakest form of visibility — any other action can dismiss it.

**Sticky**: A pinned pane that persists in the layout regardless of navigation. Multiple stickies can coexist (up to `MAX_STICKY_PANES`). Stickies are the strongest form of visibility — they persist until the user explicitly removes them.

**Precedence**: Sticky > Preview. The user's most recent action always wins for determining what stays visible.

## Interaction rules

### Single press (preview)

| Current state of pressed session | Action                                                                                                                | Layout effect                                                  |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Not previewed, not sticky        | Set as preview. Dismiss any existing preview.                                                                         | Swap preview pane content (or add slot if no preview existed). |
| Currently previewed              | Clear preview.                                                                                                        | Remove preview slot. Layout shrinks.                           |
| Sticky                           | Clear any existing non-sticky preview. Do NOT create a new preview — the session is already visible as a sticky pane. | Layout may shrink by one slot (if a preview was active).       |

### Double press (toggle sticky)

| Current state of pressed session | Action                                                                                                   | Layout effect                                           |
| -------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Not sticky                       | Add as sticky. If it was being previewed, clear the preview (now redundant — the session is pinned).     | Preview slot becomes sticky slot, or new slot added.    |
| Sticky                           | Remove sticky. **Set the removed session as the active preview.** Dismiss any previously active preview. | Sticky slot becomes preview slot. No net layout change. |

### Why un-sticky transitions to preview

When the user double-presses a sticky session, their attention is on **that** session. Removing the pane entirely would be jarring — they just interacted with it and it disappeared. Instead, the session transitions from sticky (pinned) to preview (ephemeral). The user can then navigate away to dismiss it naturally.

This also minimizes layout disruption:

- If no preview was active before un-stickying: the slot count stays the same (sticky slot becomes preview slot). Zero layout change.
- If a preview was active: the old preview is dismissed and replaced. Slot count still stays the same. Zero layout change.
- The alternative (removing the pane entirely) would always change the layout, causing a full pane rebuild.

### Guard period

After a double press (toggle sticky), a brief guard period (~300ms) suppresses the next single press on the same session. This prevents the second press of the double-press gesture from being interpreted as a new single press (which would toggle the preview).

## Invariants

1. **A session is either previewed, sticky, or neither — never both.** The reducer enforces mutual exclusivity: adding a sticky clears preview for that session; adding a preview for a sticky session is a no-op (the session is already visible).

2. **Un-sticky always transitions to preview.** Removing a sticky never leaves the session invisible. The session becomes the active preview, preserving the user's focus.

3. **Preview is ephemeral.** Any action that changes visibility (sticky toggle, new preview, tab switch) can dismiss the current preview. The user should not rely on a preview persisting.

4. **Sticky is authoritative.** A sticky pane persists across navigation, tab switches, and preview changes. Only an explicit double-press removes it.

5. **Layout stability.** The interaction model is designed to minimize full layout rebuilds. Preview swaps use lightweight pane content replacement (respawn-pane). Only changes to the total slot count trigger a full layout rebuild.

## Failure modes

| Scenario                                      | Behavior                                                                                      | Recovery                                                            |
| --------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Preview set for a session that is also sticky | Reducer clears preview; sticky takes precedence                                               | Automatic                                                           |
| Un-sticky with stale preview state            | Reducer sets preview to the un-stickied session, overwriting any stale value                  | Automatic                                                           |
| Double press detected as two single presses   | Guard period suppresses second press                                                          | Automatic; tune guard duration if still occurring                   |
| Layout rebuild on un-sticky                   | Should not happen if preview transition is correct; indicates slot count changed unexpectedly | Check that preview was set before sticky was removed in the reducer |
