# Daemon Stability — Carve-Out

## Pattern

Two recent memories highlight daemon stability as recurring friction:

1. **Always restart daemon after code changes** (Feb 9) — AIs validate against stale daemon state and miss real bugs
2. **Decouple get_context from MCP dependency** (Feb 16) — When daemon is down, we lose our critical knowledge tool

Both point to the same issue: daemon availability is too fragile, and the blast radius when it fails is too large (knowledge retrieval stops entirely).

## Actionable Insight

The daemon availability is a reliability carve-out worth documenting as a separate spec. Consider:

- What are the **daemon restart verification steps** that should be automated or standardized?
- Can **get_context become independent** of the MCP service while keeping daemon-sourced knowledge available?
- Should we have a **fallback knowledge layer** (e.g., cached docs/snippets) that works without the daemon?

The "always restart" friction repeats because the validation/verification is manual and easy to skip.

## Next Steps

- Review `project/policy/daemon-availability` to see if it adequately covers restart verification
- Investigate whether get_context can read from a local cache or git-backed doc store when MCP is unavailable
- Consider automating the "restart + verify" workflow so it's not a manual step agents have to remember
