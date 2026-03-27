# Requirements: history-role-aware

## Goal

Make `telec history` commands identity-aware so that different callers (admin,
member, customer) see only what they are authorized to see. Add a new
`telec history list` command that returns session summaries for progressive
disclosure — an agent reads summaries first, then drills into full transcripts
via `telec history show`.

## Scope

### In scope

1. **`telec history list` command** — new CLI subcommand returning session
   summaries from mirror records, ordered by recency. Accepts optional
   identity, project, and limit filters.
2. **Channel metadata in mirrors** — flow adapter metadata (origin channel and
   channel-specific identifiers) from the session into the mirror record at
   mirror-creation time.
3. **Role-aware filtering on all history commands** — scope results by caller
   identity using the existing role resolution and filtering patterns already
   established in the sessions API.
4. **Session summary in mirrors** — generate a short summary at mirror-creation
   time using the existing summarizer infrastructure and store it on the mirror
   record.

### Out of scope

- Remote computer support for `telec history list` (existing remote patterns in
  `search`/`show` are unaffected but not extended to `list`).
- Changes to `telec history search` or `telec history show` output format beyond
  adding role-based filtering.
- Web interface / API route changes for mirror listing (daemon-side filtering is
  in scope; new HTTP endpoints are not).
- Migration of existing mirrors to backfill summaries or channel metadata.

## Requirements

### R1: `telec history list` command

The new command provides a progressive-disclosure entry point for session history.

- **R1.1**: `telec history list` accepts optional flags: `--identity <email_or_key>`,
  `--project <name>`, `--limit <n>` (default: 20).
- **R1.2**: Returns a tabular summary per session: session_id, title,
  timestamp_start, timestamp_end, origin channel, summary, message_count.
  Ordered by recency (most recent first).
- **R1.3**: When `--identity` is provided, results are filtered to sessions
  matching that identity (by `source_identity` or `human_email` on the
  mirror/session).
- **R1.4**: When `--project` is provided, results are filtered to sessions in
  that project.
- **R1.5**: The command reads from the local mirrors table. [inferred]
- **R1.6**: The command is registered in the CLI surface (help text, usage,
  handler routing) following the existing pattern for `search` and `show`.

### R2: Channel metadata in mirrors

Mirror records carry the origin channel and channel-specific identifiers from
the session's adapter metadata.

- **R2.1**: At mirror-creation time, the origin channel type
  (telegram/discord/whatsapp/web/terminal) is extracted from the session and
  stored in the mirror's metadata dict.
- **R2.2**: Channel-specific identifiers (telegram `user_id`, discord
  `channel_id`/`user_id`, whatsapp `phone_number`) are extracted from the
  session's adapter metadata and stored alongside the origin channel in the
  mirror metadata dict.
- **R2.3**: The session's `adapter_metadata` and `last_input_origin` are the
  source of truth for channel information. [inferred]
- **R2.4**: Existing mirror records without channel metadata continue to
  function; the new fields are optional in the metadata dict.

### R3: Role-aware filtering

All `telec history` commands (list, search, show) apply caller-identity-based
filtering consistent with the existing role-based access control pattern used
in the sessions API.

- **R3.1**: Admin callers see all sessions across all projects and computers.
- **R3.2**: Member callers see their own sessions plus sessions marked
  `shared`. [inferred] This follows the existing grounded sessions API access
  rule (`human_email == caller OR visibility == "shared"`), which the codebase
  already implements. The current codebase does not expose a separate
  people-config project-membership mapping for session access.
- **R3.3**: Customer callers see only sessions matching their own resolved CLI
  identity. [inferred] Explicit `--identity` filtering still supports either
  `source_identity` or `human_email` (R1.3), but caller-role filtering is
  grounded in identities the current CLI auth flow can actually resolve
  (terminal email or daemon principal-derived human email).
- **R3.4**: Caller identity is resolved using the existing
  `resolve_cli_caller_role()` mechanism from `session_auth.py`.
- **R3.5**: When no caller identity can be resolved (e.g., TUI/tool client
  without auth), the current unfiltered behavior is preserved. [inferred —
  matches the existing sessions API pattern where missing identity headers
  bypass filtering.]
- **R3.6**: Filtering applies at query time in the mirror store layer so that
  all history commands benefit uniformly.

### R4: Session summary in mirrors

A short summary is generated at mirror-creation time and stored on the mirror
record.

- **R4.1**: The mirror record gains a `summary` field (nullable text) alongside
  the existing `conversation_text`.
- **R4.2**: At mirror-creation time, a one-paragraph summary is generated from
  the conversation text using the existing summarizer infrastructure
  (`_call_summarizer` pattern with structured output).
- **R4.3**: Summary generation is best-effort — if the summarizer fails or no
  API key is available, the mirror is still created without a summary.
- **R4.4**: `telec history list` displays the summary field. When no summary
  exists, it falls back to a truncated title or first message. [inferred]
- **R4.5**: The summary field is added to the mirrors table via a new database
  migration.

## Constraints

- The mirror store uses SQLite with FTS5; schema changes require a numbered
  migration following the existing convention in `teleclaude/core/migrations/`.
- The summarizer is async and uses external LLM APIs (Anthropic/OpenAI). Mirror
  generation must not block or fail if the summarizer is unavailable.
- The `MirrorRecord` dataclass is frozen; additions require updating both the
  dataclass and the upsert SQL.
- Role resolution in CLI uses TTY auth files or daemon API — both paths must be
  supported.

## Risks

- **Summarizer latency**: generating a summary at mirror-creation time adds
  latency to the AGENT_STOP/SESSION_CLOSED event handler path. Mitigation: the
  summarizer already runs in this path for session titles; summary generation
  uses the same infrastructure and is best-effort.
- **Mirror table growth**: adding a `summary` column increases storage per row.
  Mitigation: summaries are short (one paragraph); impact is negligible relative
  to `conversation_text`.

## Success Criteria

- [ ] `telec history list` returns session summaries from mirrors, filtered by
      identity/project/limit.
- [ ] Mirror records created after this change include origin channel metadata
      from the session's adapter metadata.
- [ ] Mirror records created after this change include a generated summary when
      a summarizer API key is available.
- [ ] Admin caller sees all sessions via `telec history list/search/show`.
- [ ] Member caller sees only shared sessions and their own sessions.
- [ ] Customer caller sees only their own resolved CLI identity sessions.
- [ ] Unauthenticated CLI callers retain existing unfiltered behavior.
- [ ] All existing `telec history search` and `telec history show` functionality
      continues to work unchanged (filtering is additive, not breaking).
