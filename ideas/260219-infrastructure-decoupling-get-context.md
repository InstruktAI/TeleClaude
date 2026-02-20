# Idea: Decouple get_context from MCP/Daemon Dependency

## Problem

get_context is the most critical knowledge entrypoint for agents, but it depends on MCP, which depends on the daemon being available. When the daemon goes down, agents lose their primary tool for accessing documentation, procedures, and project context.

This is a recurring friction point (Memory ID 40) — the daemon unavailability cascades into loss of context.

## Observation

- get_context is invoked by agents to load baseline doc snippets before decision-making
- MCP dependency means a daemon restart or outage completely blocks context retrieval
- Agents operating without context make poor decisions and require manual intervention
- This is classified as recurring frustration, indicating systemic impact

## Opportunity

Create a fallback context loader that works offline:

1. Cache baseline snippets locally (at agent startup or in ~/.teleclaude/cache/)
2. Agents load cached baseline by default, then attempt MCP for updates
3. If MCP is unavailable, agents still have foundation knowledge
4. When daemon recovers, cache can be refreshed

Alternative: Expose baseline context via static files that don't require MCP connection.

## Estimated Value

High. Improves agent reliability during infrastructure maintenance and provides graceful degradation.

## Risks

- Cache invalidation (ensuring agents see current policies)
- Complexity of fallback logic
- Requires changes to MCP integration layer

## Next Steps

1. Assess current get_context implementation to understand MCP dependency surface
2. Design fallback context strategy (static files vs in-process cache)
3. Prototype with memory-review job (lightweight, high-frequency user)
