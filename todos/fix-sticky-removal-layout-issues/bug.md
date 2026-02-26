# Bug:

## Symptom

When I start adding sticky's my layouts my layout changes and I see multiple pains which works beautifully. However, when I then unsticky them, the layout thing is confused. And they also don't all get removed. And there is just a screw up of the whole rendering. So I want you to investigate our logic around that. And fix it. If you can

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-26

## Investigation

Three code paths were traced for the sticky-removal flow:

1. **`getLayoutSignature` (layout.ts):** The function computes a slot count as
   `stickyIds.length + (previewId !== null ? 1 : 0)`. It did **not** check
   whether `previewId` was already one of the sticky IDs. When the user
   single-presses a sticky session (the first of a double-press to remove),
   `showPreview` is called and sets `previewSessionIdRef = sessionId`. The
   signature then jumps from N-sticky to N-sticky+1-preview (a different
   layout spec), even though `rebuildLayout` would only actually render N panes
   (the preview is excluded from specs when it equals a sticky ID). This caused
   an immediate, unnecessary full layout rebuild on every first press — panes
   were killed and recreated even though nothing structural changed. The second
   press then triggered another rebuild to remove the session, so the user saw
   panes flicker/disappear twice instead of once.

2. **`TOGGLE_STICKY` reducer (reducer.ts):** The removal branch
   (`existingIdx !== -1`) spliced the session from `stickySessions` but did
   **not** clear `sessions.preview`. The add branch already cleared preview (to
   prevent a session from being both sticky and previewed), but the remove
   branch had no equivalent cleanup. After double-pressing to unsticky a
   session, the store retained a stale `preview` pointing to the removed
   session. `SessionNode` used this to render `isPreviewed = true`, showing the
   session as "still previewed" in the UI even after its pane was killed.

3. **`useDoublePress` / `decidePreviewAction` (useDoublePress.ts):** The
   `handlePress` callback never forwarded the `isSticky` flag to
   `decidePreviewAction`, so `isSticky` always defaulted to `false`. This
   means `TreeInteractionAction.CLEAR_STICKY_PREVIEW` could never fire, and the
   `clearPreview` field on TOGGLE_STICKY decisions was always `false`. This is
   a correctness gap but was masked by the other two bugs.

## Root Cause

Two independent bugs, both triggered during the double-press unsticky flow:

**Bug 1 — signature overcounting in `getLayoutSignature`**
`getLayoutSignature` counted the preview slot unconditionally, even when the
preview session was identical to one of the sticky sessions. The actual
`rebuildLayout` logic correctly excludes preview from specs when it's already
sticky, so the signature was wider than the rendered layout. This mismatch
caused the signature to differ on the first keypress, firing a spurious full
layout rebuild (kill+recreate all panes) before the second press completed the
toggle. Result: layout thrashed visibly.

**Bug 2 — stale `preview` state after sticky removal**
The `TOGGLE_STICKY` reducer cleared `preview` when **adding** a session to
sticky (to avoid the same session being in both states), but not when
**removing**. The first press of a double-press-to-unsticky calls `showPreview`
and sets `sessions.preview`. When the second press removed the session from
`stickySessions`, `preview` was left pointing at the removed session. The UI
then showed the session as "in preview" even with no backing pane, giving the
visual impression that some sessions weren't fully removed.

## Fix Applied

Three changes committed together:

1. **`frontend/cli/lib/tmux/layout.ts` — `getLayoutSignature`**
   Compute an `effectivePreviewId` that is `null` when `previewId` is already
   in `stickyIds`. Use `effectivePreviewId` for both the slot count and the
   structural-keys list. This makes the signature match what `rebuildLayout`
   actually renders, eliminating spurious rebuilds.

2. **`frontend/lib/store/reducer.ts` — `TOGGLE_STICKY` (removal branch)**
   Added preview-clearing logic to the removal path, symmetric with the add
   path: if `sessions.preview.sessionId === sessionId` when removing, set
   `sessions.preview = null`. This ensures the UI immediately reflects that no
   session is in preview state after unstickying.

3. **`frontend/cli/hooks/useDoublePress.ts` + `SessionsView.tsx`**
   `handlePress` now accepts an optional `isSticky` parameter and forwards it
   to `decidePreviewAction`. The call site in `SessionsView` passes
   `stickyIds.has(selectedSessionId)`. This enables the `CLEAR_STICKY_PREVIEW`
   action to fire correctly and makes `clearPreview` accurate on `TOGGLE_STICKY`
   decisions.

Tests added:

- `frontend/cli/__tests__/layout.test.ts`: 8 tests covering `getLayoutSignature`
  including the core fix case (previewId in stickyIds → no extra slot).
- `frontend/lib/__tests__/reducer.test.ts`: 3 new TOGGLE_STICKY tests covering
  preview-clear on removal, no-op when preview is a different session, and
  no-op when preview is null.
