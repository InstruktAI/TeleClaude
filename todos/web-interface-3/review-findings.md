# Review Findings: web-interface-3

**Branch:** `web-interface-3`
**Commits reviewed:** 7 (`49a0e369..740fd385`)
**TypeScript compilation:** PASSES
**Review round:** 1

---

## Critical

### C1: XSS via `dangerouslySetInnerHTML` in ArtifactCard

**File:** `frontend/components/parts/ArtifactCard.tsx:30`

```tsx
dangerouslySetInnerHTML={{ __html: content }}
```

Raw HTML from the SSE stream is injected into the DOM without sanitization. The `content` field originates from the daemon's `send_result` tool call (AI-generated output). Even behind auth, prompt injection or compromised sessions could produce script tags or event handlers.

**Fix:** Sanitize with `DOMPurify.sanitize(content)` before injection, or remove the HTML rendering path entirely.

**Note:** This component is currently dead code (see I1), so the XSS is latent, not actively exploitable. But it must be fixed before the component is wired in.

---

## Important

### I1: ArtifactCard is dead code -- FR6 unmet

**File:** `frontend/components/parts/ArtifactCard.tsx` (entire file)

ArtifactCard is implemented but never imported or registered in `ThreadView.tsx`'s `MessagePrimitive.Content` components map. The assistant-ui framework renders `data` type parts as `null` when no component is registered. `data-send-result` custom parts from the SSE stream will be silently dropped.

**Requirement:** FR6 explicitly states `"data-send-result" renders as an <ArtifactCard>`.

**Action:** Either wire the component via the `Data` part mechanism (may require `useMessagePartData<T>()` or a custom data part handler), or explicitly defer to a follow-up with documented rationale.

### I2: StatusIndicator does not reflect session-level status events

**File:** `frontend/components/assistant/ThreadView.tsx:15-18`

```tsx
const status = thread.isRunning ? 'streaming' : 'idle';
```

The `StatusIndicator` supports four states (`streaming`, `idle`, `closed`, `error`) but `ThreadStatus` only derives two based on `thread.isRunning`. The `closed` and `error` config entries are dead code paths. FR6 requires `data-session-status` events to update the indicator.

**Action:** Wire `data-session-status` SSE events into state, or defer with rationale.

### I3: Reconnection with `since_timestamp` not implemented

**Requirement:** FR5 (Reconnection) -- "Use `since_timestamp` on reconnect to avoid replaying full history."

Grep for `since_timestamp`, `sinceTimestamp`, `since_time` across `frontend/` returns zero matches. Implementation plan Task 7 is marked `[x]` complete with the note "If assistant-ui/AI SDK handles reconnection natively, this may not need custom logic." However, no verification was documented.

**Action:** Verify whether the AI SDK transport handles reconnection natively. If it does, document the finding. If not, implement or explicitly defer with rationale.

### I4: No stream error handling in MyRuntimeProvider

**File:** `frontend/components/assistant/MyRuntimeProvider.tsx:25`

The `useChatRuntime` hook accepts an `onError` callback (via `ChatInit.onError`), but none is provided. When the SSE stream fails (network drop, 503, expired session), the error is swallowed by SDK defaults. The user sees the stream silently stop with no feedback. No React error boundary exists in the component tree.

**Action:** Add `onError` callback to surface stream errors to the user. Consider adding a `(chat)/error.tsx` boundary.

### I5: No dark mode syntax highlighting theme

**File:** `frontend/components/parts/MarkdownContent.tsx:6`

```tsx
import 'highlight.js/styles/github.css';
```

Only the light-mode theme is imported. The app uses `dark:prose-invert` (line 14), indicating dark mode support. Code blocks will have light background in dark mode, making text unreadable.

**Action:** Import a dark-mode-compatible theme (e.g., `github-dark-dimmed`) or conditionally load both themes with media queries.

### I6: Unused `props` parameter in MarkdownContent

**File:** `frontend/components/parts/MarkdownContent.tsx:9`

```tsx
export function MarkdownContent(props: TextMessagePartProps) {
```

The `props` parameter (containing `text`, `type`, `status`) is never used. `MarkdownTextPrimitive` reads text from React context, not props. The parameter exists to satisfy the `TextMessagePartComponent` type signature. This violates "no unused variables" policy.

**Action:** Rename to `_props` or destructure unused fields to signal intent.

---

## Suggestions

### S1: SessionPicker URL encoding

**File:** `frontend/components/SessionPicker.tsx:64`

`session_id` is interpolated into the URL without `encodeURIComponent`. Low risk (UUIDs are safe characters) but a defense-in-depth improvement.

### S2: StatusIndicator accessibility

**File:** `frontend/components/parts/StatusIndicator.tsx:21`

The colored dot `<span>` has no `aria-label` or `role`. Screen readers won't convey the status independently.

### S3: FileLink href validation

**File:** `frontend/components/parts/FileLink.tsx:11`

`data` is used as `href` without validation. A `javascript:` URI guard (allowlist `data:`, `blob:`, `https:`) would be prudent.

### S4: Session type naming collision

**Files:** `frontend/components/SessionPicker.tsx:6` and `frontend/types/next-auth.d.ts:4`

Two unrelated `Session` interfaces. Rename SessionPicker's to `AgentSession` to disambiguate.

### S5: No runtime validation at API boundary

**File:** `frontend/components/SessionPicker.tsx:25-26`

`res.json()` returns `any`. No runtime check that objects conform to `Session`. Mismatched daemon field names would produce broken UI silently.

### S6: SessionPicker error state is a dead end

**File:** `frontend/components/SessionPicker.tsx:41-46`

Error is displayed but no retry button or contextual action. 401 errors don't hint at re-login.

### S7: Collapsible pattern duplication

**Files:** `ThinkingBlock.tsx`, `ToolCallBlock.tsx`

Both duplicate the expand/collapse toggle pattern. Consider extracting a `CollapsibleSection` primitive if more collapsible types are added in Phase 4.

---

## Plan Alignment

| Requirement                                                        | Status                                                            |
| ------------------------------------------------------------------ | ----------------------------------------------------------------- |
| FR1: Streaming transport                                           | Met                                                               |
| FR2: Session selection                                             | Met                                                               |
| FR3: Reasoning parts                                               | Met                                                               |
| FR4: Tool call parts                                               | Met                                                               |
| FR5: Text/markdown parts                                           | Met                                                               |
| FR6: Custom data parts (`data-send-result`, `data-session-status`) | **Not met** -- ArtifactCard dead code, StatusIndicator incomplete |
| FR7: File parts                                                    | Met                                                               |
| FR8: Chat input                                                    | Met                                                               |
| Reconnection (`since_timestamp`)                                   | **Not met** -- no implementation, no documented deferral          |

---

## Verdict: REQUEST CHANGES

**Blocking issues:**

1. C1: XSS in ArtifactCard must be fixed (sanitize or remove HTML path)
2. I1+I2: FR6 gap -- either wire ArtifactCard + StatusIndicator to data parts, or document as explicit deferrals
3. I3: Reconnection -- verify SDK behavior or document as explicit deferral
4. I4: Stream error handling -- users must see feedback on failures

**Non-blocking but should fix:** I5 (dark mode theme), I6 (unused props)
