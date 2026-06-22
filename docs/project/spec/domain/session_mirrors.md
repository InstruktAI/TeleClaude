---
delivered_by:
  - v2-session-mirrors
  - v2-session-mirrors-cutover
description: Session Mirrors bounded context — eternal text extracts of agent sessions
  for historical search. One mirror per session, independent of session lifetime,
  text-only.
visibility: public
---

# Session Mirrors Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `session_mirrors` bounded context owns the eternal text-only extracts of agent sessions. One mirror per session, derived from the native session transcript file at session-end (or shortly after). Mirrors persist forever, independent of:

- The agent CLI's own retention (which prunes native files)
- The agent_runtime runtime ledger (which prunes session records after an operational window)

The mirror IS the durable historical record that overcomes upstream retention. Search operates exclusively on mirrors. Pure text content — no tool calls, no thinking blocks, no tool results. Default recall is conversation-first.

This context does NOT own: live session state (`agent_runtime` owns that), the persistent operational session record (lives in agent_runtime's runtime ledger with retention pruning), workflow state, knowledge content.

## Canonical fields

### Ubiquitous language

**Mirror**
: An eternal text-only extract of one agent session. Self-contained record with its own identifier. The unit of historical search.

**Mirror identifier (mirror_id)**
: UUID generated when the mirror is created. NOT the session_id from agent_runtime. The mirror's identity is independent — it doesn't FK to anything because upstream records get pruned.

**Text content**
: Pure conversation text — user input + assistant output only. Tool use, tool results, and thinking blocks are EXCLUDED. Search operates on this field.

**Summary**
: First-class human-readable description of the session. Stored on the mirror row. Computed at extraction time.

**Identity fields (inherited at extraction)**
: `agent` (claude/codex/gemini), `project_slug` (project the session ran in), `human_email` (the human who started the session), `started_at`. Inherited from the source session at extraction time. Used for search filtering.

**Native file path**
: The transcript file path at extraction time. Recorded for traceability. May no longer exist on disk (agent CLI may have pruned it; that's the whole reason the mirror exists).

**Extraction**
: The act of reading a native session transcript file and producing a mirror row. Happens at session-end (typically). The mirror is independent of the source after extraction.

**History search**
: The query interface over mirrors. Returns per-session blocks with summary + multiple query-centered text snippets. Read-only; never mutates mirrors.

### Aggregates

#### Mirror (aggregate, eternal)

- **Root:** `Mirror`
<!-- planned-change:clean-mirror-search-index -->
- **Contains:** `mirror_id` (UUID, own identity); identity fields (`agent`, `project_slug`, `human_email`, `started_at`); `summary`; `text_content` (search-indexed); `native_file_path` (at extraction time); `extracted_at`, `extraction_version`.
<!-- change:clean-mirror-search-index -->
- **Contains:** `mirror_id` (UUID, own identity); identity fields (`agent`, `project_slug`, `human_email`, `started_at`); launch classification (`command`, `slug`, `is_agent_spawn`); `summary`; `text_content` (search-indexed); `native_file_path` (at extraction time); `extracted_at`, `extraction_version`.
<!-- /planned-change:clean-mirror-search-index -->
- **Invariants:**
  - One mirror per logical session. Idempotent: re-extracting the same source produces the same content.
  - Mirror is IMMUTABLE after creation. Re-extraction creates a new mirror or replaces atomically based on extraction_version.
  - Mirror has NO foreign key to any other table — upstream records (agent_runtime.sessions) may be pruned; mirror persists.
  - `text_content` excludes tool blocks, thinking blocks, tool results. Pure conversation only.
  - Mirror is ETERNAL. No retention pruning.
- **Identifier:** `mirror_id` (UUID).
- **Lifecycle:** Built up INCREMENTALLY by the `session_history` consumer over a session's life. First window for a session creates the mirror row (identity fields, initial text_content). Subsequent windows append filtered text to text_content. Mirror is "complete" when the consumer's cursor catches up to a session that has ended — but partial mirrors are perfectly valid (a session still in flight has a partial-but-live mirror, searchable as content accumulates). Never deleted in normal operation; archival is an optional future concern.

### Domain events emitted

#### `session_mirrors.mirror.created`

- **Producer:** `session_mirrors`
- **Emitted when:** a brand-new mirror row is INSERTed (first window for a session).
- **Payload:** `mirror_id`, `agent`, `project_slug`, `human_email`, `started_at`, `created_at`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (search index refresh, history view update); audit log consumers.
- **Idempotency key:** `mirror_id`.
- **Posture:** `commit-then-emit`.

#### `session_mirrors.mirror.updated`

- **Producer:** `session_mirrors`
- **Emitted when:** an existing mirror's text_content is appended (subsequent windows).
- **Payload:** `mirror_id`, `text_appended_chars`, `updated_at`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (search index incremental refresh).
- **Idempotency key:** `(mirror_id, updated_at)`.
- **Posture:** `commit-then-emit`.

### How mirrors get built — the session_history consumer

session_history is a registered consumer of `agent_runtime.extract-window` (see `agent_runtime` domain spec). It is NOT triggered by `session.ended`. The pattern:

1. Scheduler tick or per-session turn-trigger fires
2. session_history calls `telec sessions extract-window --consumer session-history`
3. agent_runtime returns rich windows (user_text, assistant_text, thinking, tool_use, tool_result blocks) for sessions with new content
4. session_history **filters to user_text + assistant_text** and concatenates the filtered text
5. UPSERT into `session_mirrors.mirrors`:
   - If new session_id: INSERT mirror row with identity fields, initial text_content
   - If existing: UPDATE mirror's text_content with the appended new text
6. Emit `mirror.created` (on INSERT) or `mirror.updated` (on UPDATE)
7. `telec sessions ack --consumer session-history --position <X>` advances the cursor on success

This means session_mirrors does NOT subscribe to `agent_runtime.session.ended` for mirror creation. The mirror builds up continuously. Mirror lifetime is decoupled from session lifetime.

Other consumers of `session.ended` (e.g., `identity` for session-token revocation) still subscribe to it for their own purposes; session_history just doesn't need to.

### Domain events consumed

None (directly). session_history's reads come via `agent_runtime.extract-window` CLI, not via event subscription. This keeps session_mirrors as a pure persistence consumer — it has no upstream event dependency.

### Use cases

#### UC-SMI-1: Extract mirror at session end

```
Given a session ended in agent_runtime
And agent_runtime emits session.ended with native_file_path + identity fields
When session_mirrors receives the event
Then session_mirrors reads the native file (if it exists)
And extracts text-only conversation (user + assistant turns)
And computes a summary
And persists a Mirror row with mirror_id, identity fields, text_content, summary, native_file_path, extracted_at
And emits session_mirrors.mirror.created
```

#### UC-SMI-2: History search returns per-session blocks

```
Given a human runs `telec history search "<query>"`
When session_mirrors executes the search against text_content
Then it returns one block per matching mirror:
  Started: <started_at>
  Agent: <agent>
  Project: <project_slug>
  Human Email: <human_email>   # admin-only render
  Summary: <summary>
  Context:
    - "<query-centered snippet 1>"
    - "<query-centered snippet 2>"
    - ...
And NO subagent mirrors appear in results
And human_email/role rendering is admin-only (gated at render time per identity)
```

#### UC-SMI-3: Mirror persists after native file is pruned

```
Given a mirror was extracted from native file at /path/to/transcript.jsonl
And the agent CLI later prunes /path/to/transcript.jsonl (its own retention policy)
When a search query matches the mirror
Then the mirror is returned with its full text_content
And the native_file_path is shown but flagged as "may no longer exist"
And the search result is fully usable
```

#### UC-SMI-4: Mirror persists after agent_runtime row is pruned

```
Given a session ended N months ago
And agent_runtime's row for that session was pruned after the operational window
When a human searches for content from that session
Then the mirror is found by text_content
And the mirror is fully usable without any agent_runtime row existing
And the mirror_id is the lookup key, NOT the original session_id
```

#### UC-SMI-5: Re-extraction is idempotent

```
Given a mirror was extracted from a native file
And the daemon receives the same agent_runtime.session.ended event again (e.g., replay after restart)
When session_mirrors processes the event
Then it detects the existing mirror by (agent, native_session_id) match
And the extraction is a no-op (no duplicate row, no spurious event)
```

#### UC-SMI-6: Subagent transcripts excluded

```
Given a subagent transcript file exists
When the extraction pipeline encounters it
Then it is silently skipped — no mirror is created
And history search never returns subagent content
```

#### UC-SMI-7: Native file read failure is recoverable

```
Given session_mirrors receives session.ended with a native_file_path
And the file is missing or unreadable
When session_mirrors attempts extraction
Then the failure is logged with session identity for operator triage
And no mirror is created
And agent_runtime's event is not failed (the session ended either way)
And operators may manually trigger re-extraction if the file becomes readable later
```

#### v1 inventory snippets

The following concept-named feature spec snippets document the v1 implementation as it actually behaves. They are parity targets for v2 deliveries and historical reference once cutover lands.

- `project/spec/feature/session_mirrors/historical-conversation-search` — Full-text search across stored mirrors via `telec history search` and `/api/mirrors/search`.
- `project/spec/feature/session_mirrors/mirror-detail-retrieval` — Fetch one mirror by exact or prefix session id (`telec history show`, `/api/mirrors/{session_id}`).
- `project/spec/feature/session_mirrors/historical-mirror-listing` — List mirrors with identity / project / role filters (`telec history list`).
- `project/spec/feature/session_mirrors/raw-transcript-passthrough` — Stream the original transcript file via `--raw` and `/api/mirrors/{session_id}/transcript`.
- `project/spec/feature/session_mirrors/role-scoped-history-access` — Admin / member / non-member SQL filters applied to CLI search / list / show.
- `project/spec/feature/session_mirrors/cross-computer-history-federation` — `--computer` fan-out to remote mirror APIs via the local daemon's computer cache.
- `project/spec/feature/session_mirrors/mirror-reconciliation-loop` — Periodic background worker that refreshes mirrors from transcript files every 5 minutes.
- `project/spec/feature/session_mirrors/empty-transcript-tombstone` — Tombstone rows that short-circuit re-extraction for known-empty transcripts.
- `project/spec/feature/session_mirrors/session-end-mirror-fanout` — AGENT_STOP and SESSION_CLOSED dispatch through a processor registry to refresh mirrors.
- `project/spec/feature/session_mirrors/conversation-text-extraction` — Normalization rules that turn a structured transcript into the mirror's flat conversation text.
- `project/spec/feature/session_mirrors/session-summary-generation` — Best-effort one-paragraph LLM summary stored on the mirror row.
- `project/spec/feature/session_mirrors/mirror-identity-enrichment` — Cross-DB lookup of session identity + adapter channel identifier extraction.
- `project/spec/feature/session_mirrors/mirror-schema-bootstrap` — Idempotent SQLite schema + FTS5 triggers + ALTER-based column migration.

### Context map position

- **Customer-Supplier downstream of `agent_runtime`** — session_mirrors subscribes to `agent_runtime.session.ended` for the extraction trigger. agent_runtime owns the runtime ledger + native file references; session_mirrors consumes events.
- **Customer-Supplier downstream of `identity`** — search results gate `human_email`/`human_role` rendering by caller's principal role (admin-only).
- **Customer-Supplier downstream of `config`** — reads search defaults, snippet length, admin-only render policy.
- **Open Host Service to `telec history` CLI** and any HTTP/frontend caller — exposes search + list + show endpoints.
- **Open Host Service to `frontend`** for historical session display (the live timeline reads native files via agent_runtime; the historical timeline reads mirrors).
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/mirrors/` + `teleclaude/history/` modules. The v2 ACL preserves the public CLI surface (`telec history list/search/show`) during the parallel-capable phase; v1 writes disable in coordination with v2 extraction enabling.

## Allowed values

- `extraction_version`: monotonic integer; starts at 1; bumps when extraction rules change (e.g., a new way to compute summary).

<!-- planned:clean-mirror-search-index -->

- `command` / `slug`: the lifecycle command and its argument that launched the session, parsed from the transcript at extraction; null for human-driven sessions.
- `is_agent_spawn`: true when `command` is a lifecycle worker/orchestrator/integrator command. Agent-spawn mirrors are classified at extraction and excluded from default history search, so dispatched sessions never surface alongside human conversations.
- An `extraction_version` bump re-derives existing mirrors so their derived classification fields converge to the current rules.
<!-- /planned:clean-mirror-search-index -->

## Known caveats

- **Mirrors are eternal. NO retention pruning.** This is the entire point: mirrors survive when the agent CLI prunes the native file, when agent_runtime prunes the session row, when everything upstream is gone. The mirror is the durable archive.
- **Subagent transcripts EXCLUDED entirely.** Per the inherited history-search-mirror-overhaul intent: no subagent runs in results, ever. Filtered at extraction.
- **`human_email` rendering is admin-only.** Stored on the mirror row (needed for filtering); rendered conditionally based on caller's principal role. Never leaks to non-admin output.
- **Mirror has no FK** to agent_runtime.sessions or any other table. Upstream rows may be pruned; mirror persists. session_id is NOT stored on the mirror.
- **Search is text-only.** No flags for tools/thinking/tool-results. The mirror doesn't contain those fields — they were stripped at extraction. If a future use case needs richer content, that's a separate concern (read native file while it still exists, or a new aggregate; not this mirror).
- **One mirror per session.** A session is the unit of extraction. If a session was split across multiple native files (rare; some agent CLIs do this on reconnect), the extraction handles file concatenation transparently and produces ONE mirror.
- **Live timeline is NOT mirrors' job.** Mirrors are for historical search. Live timeline (the frontend showing what's happening RIGHT NOW in an active session) reads native session files via agent_runtime's file path. When the native file is gone (post-retention), live timeline for that session is no longer available — but historical search via mirrors still works.
- **Postgres TOAST handles large text_content.** Long sessions can produce very large mirrors. TOAST is transparent.
- **No projection state, no block-level normalization, no per-event tracking.** The mirror is ONE row per session. Not block-level. Not event-sourced. Simple flat extract optimized for full-text search.
