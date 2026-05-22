---
id: 'project/spec/feature/memory/memory-context-injection'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Render the most recent observations for a project as a Markdown block to inject into agent context at session start.'
---

# Memory Context Injection — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

The memory context generator turns a project's recent observations into a Markdown block that the agent CLI hook receiver prepends to each new session's context. The generator runs in two transports: an async path (`generate_context`) reachable via `GET /api/memory/inject`, and a sync path (`generate_context_sync`) consumed in-process by the hook receiver at session start. Both transports share the same observation compile-and-render pipeline: fetch the 50 most-recent observations for the project (optionally scoped by `identity_key` with inclusion-of-unscoped semantics), order them by `created_at_epoch DESC`, and render them as a `# Memory Context` Markdown section with a summary table and per-observation detail blocks.

## Canonical fields

### Use cases

#### Pre-session in-process injection (hook receiver)

```
Given the agent CLI hook receiver is handling a `session_start` event
And the resolved project is `<project_name>`
And the resolved identity_key is `<identity_key>` (or null)
When the receiver calls `_get_memory_context(project_name, identity_key=identity_key)`
Then the wrapper resolves the local DB path via `tc_paths.MAIN_DB_PATH`
And calls `generate_context_sync(project_name, db_path, identity_key=identity_key)` synchronously
And on success returns the Markdown string for inclusion in the agent's startup context
And on any exception in {OSError, RuntimeError, TypeError, ValueError} returns the empty string and the session proceeds without memory context
```

#### Sync context generation

```
Given `generate_context_sync(project, db_path, identity_key)` is invoked for a project with recent observations
When the sync engine opens a session against `db_path`
Then it queries up to 50 rows from `memory_observations WHERE project = :project [AND (identity_key IS NULL OR identity_key = :identity_key)] ORDER BY created_at_epoch DESC LIMIT 50`
And if no observations are returned, returns the empty string
And otherwise caps the timeline at 50 entries, renders it as Markdown via `render_context`, and returns the resulting string
And on any exception during the path, logs a warning and returns the empty string
```

#### HTTP context injection

```
Given any HTTP caller sends `GET /api/memory/inject?projects=<csv>[&identity_key=<key>]`
When the daemon's `inject_context` handler runs
Then it splits `projects` on `,` and picks the first non-empty token as `<project>` (empty string ⇒ returns `""`)
And calls `generate_context(<project>, identity_key=identity_key)`
And `generate_context` reads observations via the async DB path
And returns the rendered Markdown string (or `""` on empty input or exception)
```

#### Rendering shape

```
Given `render_context` receives a non-empty observation timeline
When it renders the Markdown
Then the output begins with `# Memory Context`
And includes a `## Index (<N> memories, newest first)` section with a four-column table `| # | Type | Title | When |` where `<N>` is the observation count
And the index caps at `MEMORY_INDEX_CAP` entries (default 100); when the total exceeds the cap, the heading reads `## Index (<cap> of <total> memories, newest first)` and only the newest `<cap>` rows appear in the table
And the `When` column uses relative-time formatting: `just now` (<60s), `<m>m ago` (<1h), `<h>h ago` (<24h), `<d>d ago` (≥24h)
And below the index a second section emits one `### <i>. <title>` detail block per observation containing the `**Type:**` line and the `> <narrative>` quote
And that section's heading is `## Top <MEMORY_EXPANDED_TOP_N> — Expanded` (default `Top 10 — Expanded`) when the indexed count meets or exceeds `MEMORY_EXPANDED_TOP_N`, otherwise `## Expanded`
And titles are truncated to 60 characters in the table cells
And missing titles render as `Untitled`
```

### Implementation pointers (v1)

- Async generator — `teleclaude/memory/context/builder.py:19` (`generate_context`)
- Sync generator — `teleclaude/memory/context/builder.py:36` (`generate_context_sync`)
- Re-export — `teleclaude/memory/context/__init__.py:3`
- Timeline compile — `teleclaude/memory/context/compiler.py:20` (`compile_timeline`)
- Index/expanded caps — `teleclaude/memory/context/renderer.py` (`MEMORY_INDEX_CAP = 100`, `MEMORY_EXPANDED_TOP_N = 10`)
- Markdown renderer — `teleclaude/memory/context/renderer.py:11` (`render_context`)
- Relative-time formatter — `teleclaude/memory/context/renderer.py:113` (`_relative_time`)
- HTTP entry — `teleclaude/memory/api_routes.py:115` (`GET /api/memory/inject`)
- In-process consumer — `teleclaude/hooks/receiver/_session.py:105` (`_get_memory_context`) → wraps the sync generator with broad exception suppression
- Hook-receiver call site — `teleclaude/hooks/receiver/__init__.py:355`

### Cross-context references

- `agent_runtime` — the hook receiver consumes `generate_context_sync` on `session_start`; the rendered Markdown becomes part of the agent's startup context. See `docs/project/spec/domain/agent_runtime.md`.
- `identity` — the hook receiver resolves `identity_key` from the session origin via `derive_identity_key` before calling the memory context generator; see `docs/project/spec/domain/identity.md` and `identity-key-ownership`.

## Known caveats

- **`/api/memory/inject` has no internal caller.** The hook receiver consumes the sync generator directly in-process via `_get_memory_context`. The HTTP endpoint is reachable but unexercised by the codebase. v2 design must decide whether to keep, redesign, or drop this surface.
- **Two transports, one pipeline.** The async path uses the daemon's async DB session; the sync path opens a new sync engine against `tc_paths.MAIN_DB_PATH` and disposes it. They share `compile_timeline`, `filter_by_recency`, and `render_context`.
- **Errors are swallowed.** Both transports return the empty string on any exception during read or render — a failed context generation never blocks session start or HTTP serving. The async path also logs a warning; the sync path logs a warning; the hook-receiver wrapper additionally narrows the caught set to `{OSError, RuntimeError, TypeError, ValueError}`.
- **No event emitted; no caching.** Each call re-queries the DB. There is no cache invalidation or change-notify path.
- **The 50-observation cap is hard-coded.** Callers cannot request more or fewer recent observations through this surface.
- **`projects` parameter accepts a CSV but only honors the first token.** Despite the plural name, only one project is rendered per call. The CSV shape suggests a multi-project feature was planned but never landed.
