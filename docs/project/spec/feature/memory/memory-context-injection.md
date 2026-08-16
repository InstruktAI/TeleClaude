---
description: 'Render the most recent observations for a project as a Markdown block injected into agent context at session start.'
visibility: 'public'
---

# Memory Context Injection — Spec

## What it is

The memory context generator turns a project's recent observations into a Markdown block that is prepended to each new agent session's startup context. The session-start consumer in `agent_runtime` requests the block from the `memory` service for the resolved project (optionally scoped by identity) and includes the rendered string in the session's initial context. The pipeline fetches the most-recent observations for the project, orders them newest-first, and renders them as a `# Memory Context` Markdown section with a summary index table and per-observation detail blocks.

## Canonical fields

### Use cases

#### Session-start injection

```
Given the session-start consumer is preparing context for a new agent session
And the resolved project is <project_name>
And the resolved identity scope is <identity_key> (or absent)
When it requests the memory context block from the memory service
Then the memory service returns either a rendered Markdown string or the empty string
And the empty string is returned when the project has no observations or any error occurs during read or render
And the session proceeds with whatever the service returned
```

#### Context generation

```
Given the memory service receives a context request for <project> (optionally scoped by identity)
When it builds the response
Then it fetches up to the most-recent 50 observations for that project, ordered newest-first
And if no observations are returned, it returns the empty string
And otherwise it renders the observation timeline as Markdown and returns the resulting string
And any error during read or render results in the empty string being returned
```

#### Rendering shape

```
Given the renderer receives a non-empty observation timeline
When it produces the Markdown
Then the output begins with `# Memory Context`
And includes a `## Index (<N> memories, newest first)` section with a four-column table `| # | Type | Title | When |` where `<N>` is the observation count
And the index caps at MEMORY_INDEX_CAP entries (default 100); when the total exceeds the cap, the heading reads `## Index (<cap> of <total> memories, newest first)` and only the newest <cap> rows appear in the table
And the `When` column uses relative-time formatting: `just now` (<60s), `<m>m ago` (<1h), `<h>h ago` (<24h), `<d>d ago` (≥24h)
And below the index a second section emits one `### <i>. <title>` detail block per observation containing the `**Type:**` line and the `> <narrative>` quote
And that section's heading is `## Top <MEMORY_EXPANDED_TOP_N> — Expanded` (default `Top 10 — Expanded`) when the indexed count meets or exceeds MEMORY_EXPANDED_TOP_N, otherwise `## Expanded`
And titles are truncated to 60 characters in the table cells
And missing titles render as `Untitled`
```

### Cross-context references

- `agent_runtime` — the session-start consumer requests the memory context block at session start; the rendered Markdown becomes part of the agent's startup context. See `docs/project/spec/domain/agent_runtime.md`.
- `identity` — the session-start consumer resolves an identity scope for the session before requesting the memory context; see `docs/project/spec/domain/identity.md` and `identity-key-ownership`.

## Known caveats

- **Errors are swallowed.** The injection path returns the empty string on any error during read or render — a failed context generation never blocks session start.
- **No event emitted; no caching.** Each request re-queries the underlying store. There is no cache invalidation or change-notify path.
- **The 50-observation cap is fixed.** Callers cannot request more or fewer recent observations through this surface.
- **Single-project per request.** Although the consumer-facing entry accepts a project specifier, only one project's observations are rendered per call.
