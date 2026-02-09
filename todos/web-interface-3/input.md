# Web Interface — Phase 3: Chat Interface & Part Rendering

## Context

This is phase 3 of the web-interface breakdown. Depends on phase 2
(Next.js scaffold + auth). See the parent todo's `input.md` for full context.

## Intended Outcome

Wire `useChat` with `DefaultChatTransport` to the daemon SSE endpoint and build
React components for each UIMessage part type.

## What to Build

1. **useChat integration** — `DefaultChatTransport` pointing at daemon SSE proxy via Next.js API route.
2. **API route proxy** — Next.js API route that proxies to daemon with auth headers.
3. **UIMessage part components**:
   - `<ThinkingBlock>` — collapsible reasoning (collapsed by default).
   - `<ToolCallBlock>` — tool name, collapsible args/result.
   - `<Markdown>` — react-markdown + remark-gfm.
   - `<ArtifactCard>` — send_result content.
   - `<StatusBadge>` — session status indicator.
   - `<FileLink>` — clickable link to daemon file endpoint.
4. **Chat input** — sendMessage → POST to daemon SSE endpoint.

## Verification

- useChat receives and parses SSE stream correctly.
- Each part type renders appropriately.
- User messages sent via input reach the daemon.
