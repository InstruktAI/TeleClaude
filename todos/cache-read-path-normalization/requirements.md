# Requirements - cache-read-path-normalization

## Goal

Ensure all REST read endpoints are cache-only, with consistent behavior across data types.

## Non-Goals

- No changes to write endpoints or MCP tools.
- No new UI features.

## Functional Requirements

1) **REST Reads = Cache Only**
   - All read endpoints must fetch data from cache only.
   - No direct remote pulls in REST handlers.

2) **Consistent Data Shapes**
   - Cache should provide a consistent output shape for each endpoint.
   - Any enrichment (e.g., adding computer field) is done consistently in one place.

3) **WebSocket Updates from Cache**
   - WS initial state is derived from cache.
   - WS update events originate from cache notifications.

4) **Resource-Only Responses**
   - Read endpoints return resource lists only (projects, todos, sessions, computers, availability).
   - No aggregate or mixed-resource payloads.

5) **Sessions Summary vs Detail**
   - REST returns session summary only.
   - Session detail is delivered via WebSocket subscription.

## Acceptance Criteria

- All read endpoints return data from cache without custom fetch logic.
- Cache refresh is triggered by the matrix, not by endpoint code.
- WebSocket initial state matches REST output shapes for the same data types.
