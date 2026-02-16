# DOR Report: web-interface-3 — Chat Interface & Part Rendering

## Draft Assessment

**Date:** 2026-02-16
**Phase:** draft
**Assessor:** Architect (draft mode)

## Gate Analysis

### 1. Intent & Success — PASS

- Problem: Frontend has a placeholder non-streaming adapter; daemon produces rich SSE events that go unconsumed.
- Outcome: Real-time streaming chat with typed part rendering for all UIMessage part types.
- Success criteria defined: 7 acceptance criteria covering streaming, part rendering, input, and session selection.

### 2. Scope & Size — PASS

- 12 files changed/created, all frontend. No daemon changes needed.
- Single AI session scope: the work is primarily wiring a runtime bridge + building ~6 React components.
- No cross-cutting changes — only touches the `frontend/` directory.
- Build sequence has clear parallelism (part components independent of each other).

### 3. Verification — PASS

- Each task has explicit verification steps.
- End-to-end path: open URL with sessionId → see streamed messages → type and send → see response.
- Part components can be verified visually against real daemon output.
- No test infrastructure changes required (visual/manual verification appropriate for UI work).

### 4. Approach Known — PASS (with caveat)

- `useChatRuntime` from `@assistant-ui/react-ai-sdk` is the documented bridge pattern.
- AI SDK v5 `DefaultChatTransport` SSE parsing is well-documented.
- react-markdown + remark-gfm is a proven pattern.
- **Caveat:** Custom `data-*` parts (send_result, session-status) may not surface through standard UIMessage parts. May need raw event interception. This is flagged as a risk but not blocking — fallback approaches exist.

### 5. Research Complete — NEEDS VERIFICATION

- `@assistant-ui/react-ai-sdk` documented at assistant-ui.com for AI SDK v5 integration.
- AI SDK v5 UIMessage part types documented at ai-sdk.dev.
- **Open question:** Exact version compatibility between `@assistant-ui/react` v0.12, `@assistant-ui/react-ai-sdk`, and `@ai-sdk/react`/`ai`. Need to verify peer dependency alignment before implementation.
- **Open question:** How assistant-ui surfaces custom `data-*` SSE event types as UIMessage parts. The standard types (text, reasoning, tool-call, tool-result, file) are well-documented. Custom types may require extension points.

### 6. Dependencies & Preconditions — PASS

- web-interface-1 (daemon SSE) — delivered.
- web-interface-2 (scaffold + auth) — delivered.
- No other external dependencies.
- Daemon must be running with active sessions for end-to-end testing.

### 7. Integration Safety — PASS

- All changes are additive in `frontend/`.
- Existing auth, middleware, and API routes are unchanged.
- The runtime provider replacement is contained in one file.
- Can be merged incrementally: runtime first, then components.

### 8. Tooling Impact — N/A

- No tooling or scaffolding changes.

## Open Questions

1. **Version pinning:** What exact versions of `@assistant-ui/react-ai-sdk`, `@ai-sdk/react`, and `ai` are compatible with `@assistant-ui/react` v0.12?
2. **Custom data parts:** Does `useChatRuntime` expose `data-*` custom parts as UIMessage parts, or do they need separate handling?
3. **Reconnection behavior:** Does the AI SDK transport handle SSE reconnection automatically, or does `since_timestamp` need manual wiring?

## Assumptions

1. The daemon `/api/chat/stream` endpoint works correctly (delivered in web-interface-1).
2. The Next.js `/api/chat` proxy route correctly streams SSE without buffering (delivered in web-interface-2).
3. `@assistant-ui/react-ai-sdk` supports AI SDK v5 UIMessage Stream format.
4. The `body: { sessionId }` parameter passes through to the daemon request correctly.

## Blockers

- **Dependency resolved:** web-interface-2 is now delivered (was listed as blocker in previous assessment).
- **No current blockers.** Open questions above are resolvable during implementation without external input.

## Verdict

**Draft score: 8/10** — Ready for gate assessment. Open questions are implementation-level (version pinning, custom part API) and resolvable during the first task. No architectural unknowns remain.
