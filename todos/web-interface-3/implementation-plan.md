# Implementation Plan: Web Interface Phase 3 — Chat Interface & Part Rendering

## Objective

Wire real SSE streaming into the existing assistant-ui scaffold and build typed React components for each UIMessage part type.

## Architecture Decision

**Keep `@assistant-ui/react` primitives, add AI SDK v5 bridge.**

The phase 2 scaffold uses `@assistant-ui/react` for chat layout (`ThreadPrimitive`, `MessagePrimitive`, `ComposerPrimitive`). Rather than replacing these, we add `@assistant-ui/react-ai-sdk` which bridges assistant-ui's runtime system with Vercel AI SDK v5's streaming transport. This:

- Preserves the existing layout primitives.
- Gets SSE streaming for free via AI SDK's `DefaultChatTransport`.
- Allows custom part rendering through assistant-ui's content part registration.

The `useLocalRuntime` + `ChatModelAdapter` pattern is replaced by `useChatRuntime` which internally uses `useChat` from `@ai-sdk/react`.

## [x] Task 1: Add AI SDK dependencies

**Files:** `frontend/package.json`

Add packages:

- `@assistant-ui/react-ai-sdk` — runtime bridge.
- `@ai-sdk/react` — `useChat` hook (peer dep).
- `ai` — `DefaultChatTransport` and core types (peer dep).
- `react-markdown` — markdown rendering.
- `remark-gfm` — GFM table/strikethrough support.
- `rehype-highlight` — code block syntax highlighting.
- `highlight.js` — syntax highlighting engine.

```bash
cd frontend && pnpm add @assistant-ui/react-ai-sdk @ai-sdk/react ai react-markdown remark-gfm rehype-highlight highlight.js
```

**Verification:** `pnpm build` succeeds with no type errors from new deps.

## [ ] Task 2: Replace runtime provider with AI SDK bridge

**File:** `frontend/components/assistant/MyRuntimeProvider.tsx`

Replace the `useLocalRuntime` + `ChatModelAdapter` with `useChatRuntime`:

```tsx
'use client';

import { type ReactNode } from 'react';
import { AssistantRuntimeProvider } from '@assistant-ui/react';
import { useChatRuntime } from '@assistant-ui/react-ai-sdk';

interface Props {
  sessionId: string;
  children: ReactNode;
}

export function MyRuntimeProvider({ sessionId, children }: Props) {
  const runtime = useChatRuntime({
    api: '/api/chat',
    body: { sessionId },
  });

  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}
```

Key points:

- `api: "/api/chat"` targets the existing proxy route.
- `body: { sessionId }` passes through to daemon's `ChatStreamRequest.session_id`.
- `useChatRuntime` handles SSE parsing, UIMessage construction, and streaming state.

**Verification:** Chat page loads without error; network tab shows SSE connection to `/api/chat`.

## [ ] Task 3: Wire session ID from URL and add minimal session picker

**Files:**

- `frontend/app/(chat)/page.tsx` — pass sessionId to Chat component.
- `frontend/components/assistant/Chat.tsx` — accept sessionId prop.
- `frontend/components/SessionPicker.tsx` — new: minimal session dropdown.

The chat page reads `sessionId` from URL search params. If absent, shows the session picker.

```tsx
// page.tsx
'use client';
import { useSearchParams, useRouter } from 'next/navigation';
import { Suspense } from 'react';
// ...

function ChatPageInner() {
  const searchParams = useSearchParams();
  const sessionId = searchParams?.get('sessionId');

  if (!sessionId) {
    return <SessionPicker />;
  }

  return <Chat sessionId={sessionId} />;
}
```

`SessionPicker` fetches `GET /api/sessions` and renders a list of active sessions. Clicking one navigates to `/?sessionId=<id>`.

**Verification:** Opening `/` shows session picker; clicking a session loads the chat; URL updates with sessionId.

## [ ] Task 4: Build UIMessage part components

**Directory:** `frontend/components/parts/`

### 4a: `ThinkingBlock.tsx`

- Renders `reasoning` parts.
- Collapsed by default with "Thinking..." label and chevron icon.
- Click toggles expansion to show full reasoning text.
- Subdued background (e.g., `bg-muted/50`), slightly smaller font.

### 4b: `ToolCallBlock.tsx`

- Renders `tool-call` parts.
- Shows tool name as a badge/pill (e.g., `Read`, `Bash`, `Grep`).
- Collapsible args section (collapsed by default).
- When paired `tool-result` part exists, shows result below.
- Error results get `text-destructive` styling.

### 4c: `MarkdownContent.tsx`

- Renders `text` parts via `react-markdown` + `remark-gfm` + `rehype-highlight`.
- Custom renderers for: code blocks (with copy button), links (open in new tab), tables.
- Import a highlight.js theme CSS for code styling.

### 4d: `ArtifactCard.tsx`

- Renders `data-send-result` custom parts.
- Bordered card with title bar and markdown content.
- Falls back to `<pre>` for non-markdown content.

### 4e: `StatusIndicator.tsx`

- Renders `data-session-status` events.
- Small badge: green dot for streaming, gray for idle, red for error, dash for closed.
- Placed in the chat header area.

### 4f: `FileLink.tsx`

- Renders `file` parts.
- Shows filename with a file icon.
- Click opens/downloads via daemon file endpoint.

**Verification:** Each component renders correctly with mock data; storybook-style isolation test or visual check.

## [ ] Task 5: Register part components with assistant-ui

**File:** `frontend/components/assistant/ThreadView.tsx`

Update `AssistantMessage` to dispatch rendering based on part type. assistant-ui's `MessagePrimitive.Content` supports custom content part components.

The `AssistantMessage` component maps each part type to the corresponding component from Task 4. Parts are iterated and dispatched by type: `text` → `MarkdownContent`, `reasoning` → `ThinkingBlock`, `tool-call` → `ToolCallBlock`, `tool-result` → merged into ToolCallBlock, `data-send-result` → `ArtifactCard`, `file` → `FileLink`.

Unknown part types are silently skipped.

**Verification:** Real daemon stream renders correctly with all part types visible and properly styled.

## [ ] Task 6: Enhance chat input

**File:** `frontend/components/assistant/ThreadView.tsx`

The existing `ComposerPrimitive.Input` and `ComposerPrimitive.Send` handle basic input. Enhancements:

- Shift+Enter for newlines (ComposerPrimitive may handle this already).
- Disable send while assistant is streaming (use `useThreadRuntime` status).
- Auto-focus on mount and after send.
- Placeholder text: "Type a message..." (already present).

**Verification:** Type message, press Enter, message appears in daemon session, response streams back.

## [ ] Task 7: Handle reconnection with since_timestamp

**File:** `frontend/components/assistant/MyRuntimeProvider.tsx`

When the SSE connection drops and reconnects, the transport should pass `since_timestamp` to avoid replaying the full history. This may require extending the body function to track the last received timestamp.

If assistant-ui/AI SDK handles reconnection natively, this may not need custom logic. Verify behavior and add `since_timestamp` only if history replays on reconnect.

**Verification:** Simulate network drop; on reconnect, no duplicate messages appear.

## [ ] Task 8: Status indicator in chat header

**File:** `frontend/app/(chat)/page.tsx`

Add `StatusIndicator` to the header area. It reads the latest `data-session-status` event from the stream. The status is derived from the assistant-ui runtime's streaming state + custom data parts.

**Verification:** Header shows "streaming" while daemon is sending, transitions to "idle" when done.

## Files Changed

| File                                                  | Change                                    |
| ----------------------------------------------------- | ----------------------------------------- |
| `frontend/package.json`                               | Add AI SDK + markdown deps                |
| `frontend/components/assistant/MyRuntimeProvider.tsx` | Replace local runtime with AI SDK bridge  |
| `frontend/components/assistant/Chat.tsx`              | Accept sessionId prop                     |
| `frontend/components/assistant/ThreadView.tsx`        | Part type dispatching in AssistantMessage |
| `frontend/app/(chat)/page.tsx`                        | Session ID from URL, header status        |
| `frontend/components/SessionPicker.tsx`               | New: minimal session list                 |
| `frontend/components/parts/ThinkingBlock.tsx`         | New: reasoning renderer                   |
| `frontend/components/parts/ToolCallBlock.tsx`         | New: tool call renderer                   |
| `frontend/components/parts/MarkdownContent.tsx`       | New: markdown renderer                    |
| `frontend/components/parts/ArtifactCard.tsx`          | New: send_result renderer                 |
| `frontend/components/parts/StatusIndicator.tsx`       | New: session status badge                 |
| `frontend/components/parts/FileLink.tsx`              | New: file link renderer                   |

## Build Sequence

1. Task 1 (deps) → Task 2 (runtime) → Task 3 (session wiring) — sequential, each depends on prior.
2. Task 4 (part components) — can be done in parallel once Task 2 is complete.
3. Task 5 (part registration) — after Tasks 2 and 4.
4. Task 6 (input) + Task 7 (reconnection) + Task 8 (status) — after Task 5.

## Risks

1. **assistant-ui + AI SDK v5 compatibility** — `@assistant-ui/react-ai-sdk` version must match both `@assistant-ui/react` v0.12 and AI SDK v5. Pin versions carefully.
2. **Custom data parts** — AI SDK may not expose `data-*` parts through the standard UIMessage model. May need to intercept raw SSE events or use assistant-ui's extension points. Fall back to raw event parsing if needed.
3. **Streaming proxy** — The existing `/api/chat` route already streams SSE. Verify the AI SDK transport handles the proxy correctly (no buffering, proper headers forwarded).
4. **Tool call / tool result pairing** — AI SDK may auto-pair these or they may arrive as separate parts. Verify and handle both cases.

## Verification

- Daemon SSE stream consumed correctly via `useChatRuntime`.
- Each part type renders with appropriate component.
- Message send → daemon ingestion → response stream → UI update works end-to-end.
- Session picker allows switching between sessions.
- No console errors or React hydration mismatches.
