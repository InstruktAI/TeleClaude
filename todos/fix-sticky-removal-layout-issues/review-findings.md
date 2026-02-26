# Review Findings: fix-sticky-removal-layout-issues

## Verdict: APPROVE

## Summary

Clean, well-targeted bug fix addressing three independent root causes in the sticky-removal flow. Each fix is minimal and correctly mirrors existing codebase patterns. Investigation and documentation in `bug.md` (committed in e23521e9) are thorough. Tests are deterministic, behavior-focused, and cover the core fix scenarios with positive and negative cases. All 213 frontend tests and 2143 Python unit tests pass.

## Paradigm-Fit Assessment

1. **Data flow**: Fix operates within the established data layer — Immer-based reducer for state, tmux layout signature for change detection, gesture state machine for interaction. No bypasses.
2. **Component reuse**: The `isSticky` parameter is threaded through existing interfaces (`handlePress`, `decidePreviewAction`) rather than introducing parallel mechanisms. Existing `effectivePreviewId` logic mirrors `rebuildLayout`'s existing exclusion at `useTmux.ts:112`.
3. **Pattern consistency**: The preview-clear in the TOGGLE_STICKY removal branch follows the identical pattern already in the add branch (reducer.ts:118-124). Symmetric, as expected.

## Critical

(none)

## Important

(none)

## Suggestions

### S1: `CLEAR_STICKY_PREVIEW` routes to `onPreview` — cosmetic flicker between presses

**File**: `frontend/cli/hooks/useDoublePress.ts:54-56`

When the first press of a double-press-to-unsticky fires, `CLEAR_STICKY_PREVIEW` routes to `onPreview(itemId)`, which dispatches `SET_PREVIEW`. Between press 1 and press 2, the store briefly holds `preview: { sessionId }` for the sticky session. The layout signature fix prevents a tmux rebuild (the signature normalizes this away), but any React-level rendering that checks `isPreviewed` may briefly reflect the state.

This is **pre-existing behavior** — before this fix, `isSticky` was always `false` so `PREVIEW` fired instead of `CLEAR_STICKY_PREVIEW`, producing the same `SET_PREVIEW` dispatch. The fix did not introduce or worsen this. A future improvement could make `CLEAR_STICKY_PREVIEW` a no-op in the hook switch to eliminate the intermediate state entirely.

### S2: Signature stability depends on stickyIds insertion order

**File**: `frontend/cli/lib/tmux/layout.ts:206`

`structuralKeys` includes `stickyIds` verbatim. If `stickySessions` were ever reordered (e.g., during a `SYNC_SESSIONS` prune), the signature would differ for the same logical set, triggering a spurious rebuild. In practice, `stickySessions` is push/splice-maintained so order is stable. A defensive `[...stickyIds].sort()` in structuralKeys construction would make this order-invariant. Low priority — the current callers guarantee order.

### S3: No integration test for `useDoublePress` isSticky forwarding

**File**: `frontend/cli/hooks/useDoublePress.ts:42-43`

The `isSticky` parameter threading from `SessionsView` → `useDoublePress` → `gesture.ts` is untested at the hook integration level. The gesture state machine has full coverage for `isSticky` in `gesture.test.ts` (22 tests), and the hook is thin glue code (6-line switch). Risk is low, but a `renderHook` test would catch regressions where the parameter stops being forwarded. Consider as future hardening.

## Why No Issues (Zero-Finding Justification)

1. **Paradigm-fit verified**: `effectivePreviewId` logic in `getLayoutSignature` (layout.ts:196-197) mirrors the exclusion condition in `rebuildLayout` (useTmux.ts:112) exactly: `previewId && !stickyIds.includes(previewId)`. The reducer removal branch (reducer.ts:107-113) follows the same preview-clear pattern as the add branch (reducer.ts:118-124). The `isSticky` parameter threads through existing interfaces without new abstractions.
2. **Requirements met**: Bug symptom was "layout confused on unsticky + sessions not fully removed." Root cause 1 (signature overcounting) prevented by `effectivePreviewId` normalization — verified by layout.test.ts:26-31 (same signature when preview is sticky). Root cause 2 (stale preview) prevented by conditional clear in reducer removal branch — verified by reducer.test.ts:199-206 (preview cleared on sticky removal). Root cause 3 (isSticky never forwarded) fixed by parameter threading — verified by existing gesture.test.ts coverage.
3. **Copy-paste duplication checked**: The preview-clear block in the removal branch (reducer.ts:107-113) is structurally identical to the add branch (reducer.ts:118-124). This is intentional symmetry, not copy-paste — both branches handle the same invariant (a session shouldn't be both sticky and previewed) for their respective transitions.
4. **Logging hygiene**: No `console.log`, debug probes, or leftover instrumentation found in any changed file.
5. **Manual verification gap**: This is a TUI/tmux layout change. Full manual verification requires a running tmux session with multiple stickied panes. The test suite exercises the state machine, reducer, and layout signature logic. The tmux rendering path (`renderLayout`, `rebuildLayout`) is exercised indirectly through signature correctness but not end-to-end in tests. This is consistent with the project's testing strategy (unit + functional, not full e2e for tmux).
