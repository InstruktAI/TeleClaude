# Reconnection with since_timestamp - Gap Analysis

## Status: Not Implemented

## Requirement

FR5 specifies: "Use `since_timestamp` on reconnect to avoid replaying full history."

## Investigation Findings

### AI SDK & assistant-ui Support

- Searched `@assistant-ui/react-ai-sdk` and `ai` package type definitions
- No built-in reconnection or resumption APIs found
- No `since_timestamp` parameter support in AssistantChatTransport

### Current Behavior

- On page reload or network disconnect, the full chat history is replayed from the start
- No mechanism to resume from a specific timestamp

## Implementation Requirements

To implement this feature, we would need:

1. **Client-side**:
   - Track the timestamp of the last received message
   - Store this in session storage or a persistent mechanism
   - Pass `since_timestamp` query parameter when reconnecting

2. **API endpoint**:
   - Modify `/api/chat` to accept and honor `since_timestamp` parameter
   - Filter SSE events to only send those after the timestamp

3. **Transport layer**:
   - Extend AssistantChatTransport or create custom transport
   - Add reconnection logic with timestamp tracking

## Recommendation

**Defer to Phase 4** - This is a UX enhancement, not a blocker for basic functionality. The current behavior (replaying full history) is suboptimal but functional for:

- Short sessions (< 50 messages)
- Stable network connections
- Development/testing

For production with long sessions, this should be prioritized.

## Related Issues

- I3 in review-findings.md
