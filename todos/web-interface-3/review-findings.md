# Review Findings: web-interface-3

**Branch:** `web-interface-3`
**Commits reviewed:** 15 (`49a0e369..87edcd29`)
**Review round:** 2

---

## Round 2 Assessment

Round 1 identified 1 critical, 6 important, and 7 suggestion-level findings. Fixes were applied in commits `dd6428e7..87edcd29`. This round evaluates those fixes and identifies new issues introduced by the fix commits.

### Round 1 Fix Evaluation

| R1 Issue                       | Fix Status                     | R2 Assessment                                                                   |
| ------------------------------ | ------------------------------ | ------------------------------------------------------------------------------- |
| **C1: XSS in ArtifactCard**    | DOMPurify added (dd6428e7)     | **Incomplete** — `dompurify` package missing from `package.json` (see C1 below) |
| **I4: Stream error handling**  | onError + banner (04b055d7)    | **Incomplete** — error banner never clears (see I1 below)                       |
| **I5: Dark mode theme**        | CSS media queries (5a687432)   | **Incomplete** — invalid CSS `@import` nesting (see C2 below)                   |
| **I6: Unused props**           | Renamed to `_props` (ef4390a2) | ✅ Complete                                                                     |
| **I1: ArtifactCard wiring**    | Documented as TODO (0cd76579)  | ✅ Acceptable deferral — requires framework API research                        |
| **I2: StatusIndicator wiring** | Documented as TODO (9275b909)  | ✅ Acceptable deferral — requires custom SSE event interception                 |
| **I3: Reconnection**           | Gap analysis doc (756b2c29)    | ✅ Acceptable deferral — documented with Phase 4 recommendation                 |

---

## Critical

### C1: Missing `dompurify` dependency

**File:** `frontend/components/parts/ArtifactCard.tsx:5`

```tsx
import DOMPurify from 'dompurify';
```

The C1 XSS fix added `DOMPurify.sanitize()` but `dompurify` was never added to `package.json`. Confirmed: the package does not exist in `node_modules`. The import compiles only because ArtifactCard is dead code (not in the import graph of any page), so Next.js never resolves the module.

When ArtifactCard is wired in (Phase 4), this will cause a build failure.

**Fix:** `pnpm add dompurify && pnpm add -D @types/dompurify`

### C2: Invalid CSS — `@import` nested inside `@media`

**File:** `frontend/styles/highlight-theme.css:1-9`

```css
@media (prefers-color-scheme: light) {
  @import 'highlight.js/styles/github.css';
}
@media (prefers-color-scheme: dark) {
  @import 'highlight.js/styles/github-dark-dimmed.css';
}
```

Per the CSS specification, `@import` must appear at the top level of a stylesheet before any other rules. Nesting `@import` inside `@media` blocks is invalid CSS. The PostCSS config only includes `@tailwindcss/postcss` — no `postcss-import` plugin that might handle this non-standard pattern. Browsers will ignore the nested imports, meaning neither theme loads.

**Fix:** Use top-level `@import` with media query condition:

```css
@import 'highlight.js/styles/github.css' (prefers-color-scheme: light);
@import 'highlight.js/styles/github-dark-dimmed.css' (prefers-color-scheme: dark);
```

---

## Important

### I1: Error banner never clears in MyRuntimeProvider

**File:** `frontend/components/assistant/MyRuntimeProvider.tsx:16-46`

The `onError` callback sets error state, but `setError(null)` is never called anywhere. Once a transient stream error occurs:

- The banner persists even after the stream recovers
- Switching sessions (new `sessionId` prop) does not clear it
- No dismiss button exists
- Users see a stale error for the remainder of the page lifecycle

**Fix:** At minimum, clear error when `sessionId` changes:

```tsx
useEffect(() => {
  setError(null);
}, [sessionId]);
```

And add a dismiss button to the error banner.

---

## Suggestions (carried from R1, still applicable)

- **S1:** SessionPicker URL encoding — `encodeURIComponent` for session_id
- **S2:** StatusIndicator accessibility — `aria-label` on status dot
- **S3:** FileLink href validation — guard against `javascript:` URIs
- **S6:** SessionPicker error state — add retry button

---

## Documented Deferrals (Accepted)

The following gaps from R1 are documented with clear rationale and recommended for Phase 4:

1. **ArtifactCard wiring (FR6 partial)** — assistant-ui lacks a direct registration path for custom data parts. TODO in `ThreadView.tsx:14-16` with research pointers.
2. **StatusIndicator session-status events (FR6 partial)** — requires intercepting custom SSE events outside the message flow. TODO in `ThreadView.tsx:20-26`.
3. **Reconnection with `since_timestamp`** — no native SDK support. Gap analysis at `frontend/docs/reconnection-gap.md`.

---

## Plan Alignment

| Requirement                      | Status                                           |
| -------------------------------- | ------------------------------------------------ |
| FR1: Streaming transport         | Met                                              |
| FR2: Session selection           | Met                                              |
| FR3: Reasoning parts             | Met                                              |
| FR4: Tool call parts             | Met                                              |
| FR5: Text/markdown parts         | Met (pending C2 CSS fix for dark mode highlight) |
| FR6: Custom data parts           | Deferred — documented with rationale             |
| FR7: File parts                  | Met                                              |
| FR8: Chat input                  | Met                                              |
| Reconnection (`since_timestamp`) | Deferred — documented with rationale             |

---

## Fixes Applied

### Round 1 Fixes (Commits dd6428e7 - 87edcd29)

| Issue                          | Status        | Commit   | Notes                                                            |
| ------------------------------ | ------------- | -------- | ---------------------------------------------------------------- |
| **C1: XSS in ArtifactCard**    | ⚠️ Incomplete | dd6428e7 | DOMPurify.sanitize() added but package missing from package.json |
| **I6: Unused props**           | ✅ Fixed      | ef4390a2 | Renamed to `_props`                                              |
| **I5: Dark mode theme**        | ⚠️ Incomplete | 5a687432 | Invalid CSS @import nesting — themes don't load                  |
| **I4: Stream error handling**  | ⚠️ Incomplete | 04b055d7 | onError added but error banner never clears                      |
| **I1: ArtifactCard wiring**    | 📝 Documented | 0cd76579 | Phase 4 deferral                                                 |
| **I2: StatusIndicator wiring** | 📝 Documented | 9275b909 | Phase 4 deferral                                                 |
| **I3: Reconnection**           | 📝 Documented | 756b2c29 | Phase 4 deferral with gap analysis                               |

---

## Verdict: REQUEST CHANGES

**Blocking (must fix):**

1. **C1:** Add `dompurify` (and `@types/dompurify`) to `package.json`
2. **C2:** Fix CSS `@import` syntax — use top-level imports with media conditions
3. **I1:** Add error clearing mechanism to MyRuntimeProvider (at minimum on sessionId change + dismiss button)

**Non-blocking:** S1, S2, S3, S6 remain open suggestions for future improvement.
