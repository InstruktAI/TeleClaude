# Requirements - smart-cache-policy-matrix

## Goal

Define a single policy matrix that drives cache behavior for all data types. The cache must serve stale data immediately and refresh in the background when TTL expires.

## Non-Goals

- No endpoint-specific refresh logic.
- No new client features or UI changes beyond consistent data delivery.
- No changes to MCP tooling.

## Functional Requirements

1) **Policy Matrix as Source of Truth**
   - Cache behavior is defined by a single matrix (data type, scope, TTL, warmup flag).
   - Every data read path consults the matrix.

2) **Serve Stale + Refresh**
   - All reads return cached data immediately, even if stale.
   - When stale, a background refresh is scheduled based on matrix rules.

3) **Warmup**
   - Data types marked as warmup are refreshed once on daemon startup.
   - Projects are warmup-enabled by default.

4) **Cache Notifications**
   - Cache publishes updates to subscribers on refresh completion.
   - REST/WebSocket clients receive updates via existing push flow.

5) **Resource-Only Refresh**
   - Refreshers fetch resource lists only (projects, todos, sessions, computers, availability).
   - No aggregate fetches or mixed resource payloads.

6) **Project Invalidation Signal**
   - Project list invalidation is triggered by a small heartbeat digest.
   - Digest changes override TTL and schedule immediate refresh.

7) **Session Summary Only**
   - Cache stores only session summaries.
   - Session detail and live events are delivered via WebSocket subscriptions.

## Data Types in Scope

- Computers
- Projects
- Todos
- Sessions
- Agent availability

## Acceptance Criteria

- A single policy matrix exists and is used for all cache decisions.
- REST handlers do not implement custom refresh logic.
- Stale data is returned immediately for all cache-backed reads.
- Background refresh occurs based on TTL and policy matrix.
- Projects are available from cache immediately after daemon startup (stale is acceptable).
- Project digest changes trigger refresh even if TTL is not expired.
