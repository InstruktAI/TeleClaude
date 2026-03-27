# Implementation Plan: history-role-aware

## Overview

Make `telec history` commands identity-aware and add `telec history list` for
progressive disclosure. One coherent behavior: role-aware history with session
summaries.

**Atomicity verdict:** Atomic. The list command requires the summary, which
requires the mirror generation changes, which requires the migration. Splitting
would create a half-working codebase. ~480 lines of production changes across
tightly coupled modules.

## Xfail Test Specifications

The following expected-failure tests are delivered as part of this plan. Each
task's verification section identifies which spec tests it must make GREEN.

| Test file                                       | Function name                                                                                   |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `tests/unit/mirrors/test_store.py`              | `TestHistoryRoleAwareSpecs::test_list_mirrors_matches_source_identity_or_human_email`           |
| `tests/unit/mirrors/test_store.py`              | `TestHistoryRoleAwareSpecs::test_get_mirror_allows_member_owned_or_shared_records`              |
| `tests/unit/mirrors/test_generator.py`          | `TestGenerateMirrorSync::test_generate_mirror_persists_summary_visibility_and_channel_metadata` |
| `tests/unit/mirrors/test_processors.py`         | `TestProcessMirrorEvent::test_process_mirror_event_passes_expanded_session_context`             |
| `tests/unit/history/test_search.py`             | `TestShowTranscript::test_show_transcript_passes_caller_context_to_get_mirror`                  |
| `tests/unit/history/test_search.py`             | `TestRoleAwareHistorySpecs::test_display_combined_history_passes_caller_context`                |
| `tests/unit/cli/telec/handlers/test_history.py` | `test_handle_history_list_parses_filters_and_delegates`                                         |

All are marked with strict `@pytest.mark.xfail(...)` expected-failure markers.
The builder removes each marker as the first action for the task that satisfies
it.

## Tasks

### Task 1: DB migration — add `summary`, `human_email`, and `visibility` to mirrors [x]

**What:** New migration `033_add_mirror_summary_and_human_email.py` that adds three
nullable/defaulted columns to the mirrors table.

**Why:** The `summary` column stores the LLM-generated session summary for
progressive disclosure (R4.1, R4.5). The `human_email` column stores the session
owner's email for efficient role-based filtering at query time (R3.6). Without
`human_email` on the mirror, every filtered query would require a JOIN against the
sessions table — which uses SQLAlchemy/aiosqlite while mirrors use raw sqlite3,
making cross-table queries impractical. The `visibility` column mirrors the
session's `visibility` field at mirror-creation time, enabling the member access
pattern from the sessions API (`human_email = caller OR visibility = 'shared'`,
matching `_filter_sessions_by_role` in `sessions_routes.py` line 100) to work
uniformly in the mirror store layer (R3.2).

**Changes:**

- Create `teleclaude/core/migrations/033_add_mirror_summary_and_human_email.py`
- `up`:
  - `ALTER TABLE mirrors ADD COLUMN summary TEXT`
  - `ALTER TABLE mirrors ADD COLUMN human_email TEXT`
  - `ALTER TABLE mirrors ADD COLUMN visibility TEXT DEFAULT 'private'`
  - `CREATE INDEX idx_mirrors_human_email ON mirrors(human_email)` for
    filtering performance
- `down`: SQLite cannot drop columns; rebuild table without the new columns
  following the pattern in migration 028.

**Verification:**

- Migration runs without error on a DB with existing mirrors.
- Existing mirrors have NULL summary and human_email, and 'private' visibility
  (no backfill required per out-of-scope constraint).
- Test: migration up/down is idempotent.

**Satisfies:** R4.5 (summary field via migration), R3.6 (filtering at query
time requires human_email on the mirror), R3.2 (visibility enables member
access matching sessions API pattern).

---

### Task 2: Expand MirrorRecord, SessionMirrorContext, and SQL [x]

**What:** Add `summary`, `human_email`, and `visibility` fields to `MirrorRecord`.
Expand `SessionMirrorContext` to carry session fields needed at mirror-creation
time. Update all SQL in `store.py` to read/write the new columns.

**Why:** The dataclass is frozen — all field additions must be coordinated with
the SQL. `SessionMirrorContext` must carry session data that the generator needs
at mirror-creation time (R2.1, R2.2, R4.2). Without expanding the context, the
generator would need its own DB query to the sessions table.

**Session origin landscape (informs context design):**

Sessions originate from 8 paths (`InputOrigin`): telegram, discord, whatsapp,
web, redis, api, terminal, hook. Only 3 (telegram, discord, whatsapp) populate
`adapter_metadata` with channel-relevant data (user_id, channel_id,
phone_number). The other 5 have empty or transport-only adapter_metadata.

The mirror needs two things from the session:

1. **Origin channel** — `last_input_origin` on the session. Always present,
   always authoritative. This is the source of truth for "where did this session
   come from."
2. **Channel identifiers** — platform-specific IDs (telegram user_id, discord
   user_id/channel_id, whatsapp phone_number). Only meaningful when origin is
   telegram/discord/whatsapp. Extracted from `adapter_metadata` JSON, gated by
   origin type.

`SessionMirrorContext` carries both fields so the generator can build channel
metadata without touching the sessions table again. The term "adapter_metadata"
does not appear in the mirror layer — the mirror speaks "origin channel" and
"channel identifiers."

**Changes in `teleclaude/mirrors/store.py`:**

- Add `summary: str | None = None` to `MirrorRecord` (after `source_identity`,
  before other optional fields).
- Add `human_email: str | None = None` to `MirrorRecord`.
- Add `visibility: str = 'private'` to `MirrorRecord`.
- Add to `SessionMirrorContext`:
  - `human_email: str | None = None`
  - `visibility: str | None = None` — from session's `visibility` field
    (`Session.visibility` defaults to `"private"`).
  - `last_input_origin: str | None = None` — from session's `last_input_origin`
  - `adapter_metadata_json: str | None = None` — raw session adapter_metadata
    column; the generator parses this only when `last_input_origin` is
    telegram/discord/whatsapp, ignores it otherwise.
- Update `get_session_context` SQL: add `human_email`, `visibility`,
  `last_input_origin`, and `adapter_metadata` to the SELECT from the sessions
  table.
- Update `upsert_mirror` SQL: include `summary`, `human_email`, and `visibility`
  in INSERT and ON CONFLICT UPDATE clauses.
- Update `get_mirror` SQL: include `summary`, `human_email`, and `visibility` in
  SELECT, and populate them in the returned `MirrorRecord`.
- Update `search_mirrors` SQL: include `human_email`, `visibility`, and
  `source_identity` in SELECT (needed for post-query role filtering in Task 6).
  Add `human_email`, `visibility`, and `source_identity` to `MirrorSearchResult`
  dataclass.

**Verification:**

- `upsert_mirror` with summary, human_email, and visibility succeeds.
- `get_mirror` returns the stored summary, human_email, and visibility.
- `get_session_context` returns human_email, visibility, last_input_origin, and
  adapter_metadata_json from the session row.
- Existing callers of these functions continue to work (new fields are optional
  with defaults).

**Xfail specs made green:**

- `tests/unit/mirrors/test_store.py::TestHistoryRoleAwareSpecs::test_list_mirrors_matches_source_identity_or_human_email`
- `tests/unit/mirrors/test_processors.py::TestProcessMirrorEvent::test_process_mirror_event_passes_expanded_session_context`

**Satisfies:** R4.1 (summary field on MirrorRecord), R2.3 (session fields
available via context for channel metadata extraction), R3.6 (human_email for
query-time filtering), R3.2 (visibility field mirrors session visibility).

---

### Task 3: Channel metadata, human_email, and visibility flow into mirror generation [x]

**What:** At mirror-creation time, derive channel metadata from the session's
`last_input_origin` and (for adapter origins only) its `adapter_metadata`. Flow
human_email and visibility into the mirror record.

**Why:** R2.1 and R2.2 require origin channel and channel-specific identifiers
on the mirror. The session's `last_input_origin` is the source of truth for
origin channel (R2.3). Channel identifiers only exist for 3 of 8 origins
(telegram, discord, whatsapp) — the others have empty or transport-only
adapter_metadata. The generator must gate identifier extraction by origin type
to avoid parsing irrelevant data. `visibility` must be passed through so the
member access pattern in Task 5 works correctly (R3.2).

**Changes in `teleclaude/mirrors/processors.py`:**

- In `process_mirror_event`: pass `context.human_email`,
  `context.visibility`, `context.last_input_origin`, and
  `context.adapter_metadata_json` to `generate_mirror`.

**Changes in `teleclaude/mirrors/generator.py`:**

- Add `human_email: str | None = None`,
  `visibility: str = 'private'`,
  `last_input_origin: str | None = None`, and
  `channel_identifiers: dict[str, str] | None = None` parameters to both
  `generate_mirror` and `generate_mirror_sync`.
- New `_extract_channel_identifiers(origin: str, raw_json: str | None) ->
dict[str, str]` helper:
  - If origin not in ("telegram", "discord", "whatsapp"): return empty dict.
    Terminal, web, API, redis sessions have no platform identifiers in
    adapter_metadata.
  - Parse `raw_json` via `SessionAdapterMetadata.from_json()`.
  - telegram → `{"user_id": str(tg.user_id)}` if present.
  - discord → `{"user_id": dc.user_id, "channel_id": str(dc.channel_id)}`
    where present.
  - whatsapp → `{"phone_number": wa.phone_number}` if present.
- In `generate_mirror_sync`: build `channel_metadata` dict for the mirror's
  metadata:
  ```
  {"origin_channel": last_input_origin, **channel_identifiers}
  ```
  Merge into the mirror's metadata dict alongside existing `transcript_path`
  and `agent` keys.
- Set `human_email` and `visibility` on the MirrorRecord.
- Call `_extract_channel_identifiers` in the processor before passing to
  generator, so the generator receives pre-extracted identifiers and never
  sees raw adapter_metadata.

**Verification:**

- Mirror from telegram session: metadata has `origin_channel: "telegram"` and
  `user_id`.
- Mirror from terminal session: metadata has `origin_channel: "terminal"`, no
  channel identifiers (terminal sessions have no adapter-level IDs).
- Mirror from API session: metadata has `origin_channel: "api"`, no channel
  identifiers.
- Mirror from redis session: metadata has `origin_channel: "redis"`, no
  channel identifiers (redis adapter_metadata is transport, not identity).
- Mirror from session without last_input_origin: metadata has no origin_channel
  key (backward compatible, R2.4).
- Mirror record stores human_email and visibility from the session.

**Xfail specs made green:**

- `tests/unit/mirrors/test_generator.py::TestGenerateMirrorSync::test_generate_mirror_persists_summary_visibility_and_channel_metadata`
- `tests/unit/mirrors/test_processors.py::TestProcessMirrorEvent::test_process_mirror_event_passes_expanded_session_context`

**Satisfies:** R2.1 (origin channel stored), R2.2 (channel-specific identifiers
stored for adapter origins), R2.3 (last_input_origin + adapter_metadata are
source of truth), R2.4 (existing records unaffected), R3.6 (human_email stored
for filtering), R3.2 (visibility stored for member filtering).

---

### Task 4: Summary generation at mirror-creation time [x]

**What:** Generate a one-paragraph session summary at mirror-creation time and
store it on the mirror record.

**Why:** R4.2 requires summary generation using the existing summarizer
infrastructure. The summary is what `telec history list` displays (R4.4). The
async `generate_mirror` function is the natural place since the summarizer is
async and uses external LLM APIs.

**Changes in `teleclaude/mirrors/generator.py`:**

- Refactor: extract the conversation-text-building logic from
  `generate_mirror_sync` into a new `_prepare_mirror_data(...)` sync helper that
  returns the built MirrorRecord (or None if no messages). The upsert stays in
  `generate_mirror_sync`.
- In the async `generate_mirror`:
  1. Call `_prepare_mirror_data` via `asyncio.to_thread` to build the record.
  2. If record is not None, attempt summary generation: call
     `_generate_session_summary(record.conversation_text)` — a new async helper.
  3. If summary succeeds, replace the record's summary field (using
     `dataclasses.replace`).
  4. Upsert the final record via `asyncio.to_thread(upsert_mirror, ...)`.
- `_generate_session_summary(conversation_text: str) -> str | None`:
  - Build a prompt asking for a one-paragraph session summary.
  - Call the existing `_call_summarizer` from `teleclaude/core/summarizer.py`
    with `SUMMARY_SCHEMA` and `_parse_summary_response`.
  - Return the summary string, or None on any exception (best-effort, R4.3).
- `generate_mirror_sync` continues to work for the reconciliation worker path
  (without summary generation — the worker runs sync and summary is best-effort).

**Verification:**

- Mirror created via async path (event handler) includes a summary when API key
  is available.
- Mirror created via async path without API key succeeds without summary (R4.3).
- Mirror created via sync path (worker) succeeds without summary (no regression).
- Summary is a reasonable one-paragraph description of the session.

**Satisfies:** R4.2 (summary generated at mirror-creation time), R4.3
(best-effort — failure does not block mirror creation), R4.4 (summary stored and
available for list command).

---

### Task 5: `list_mirrors` store function with role-based filtering [x]

**What:** New `list_mirrors()` function in `store.py` that queries mirrors with
role-based access control and optional project/identity filters.

**Why:** R1.5 requires reading from the local mirrors table. R3.6 requires
filtering at query time in the mirror store layer so all history commands benefit.
A shared store function ensures consistent filtering across list/search/show.
Role filtering uses the `visibility` column (added in Task 1) to match the member
access semantics established in `_filter_sessions_by_role` (sessions_routes.py
line 100): members see own sessions plus shared sessions. Explicit `--identity`
filtering still matches by `human_email OR source_identity` to satisfy R1.3,
while role-based customer access stays grounded in caller identities the current
CLI auth flow can actually resolve.

**Changes in `teleclaude/mirrors/store.py`:**

- New function:
  ```
  def list_mirrors(
      *,
      limit: int = 20,
      project: str | None = None,
      identity: str | None = None,
      caller_email: str | None = None,
      caller_role: str | None = None,
      db: object | None = None,
  ) -> list[MirrorRecord]:
  ```
- Query logic:
  - Base: `SELECT ... FROM mirrors ORDER BY
COALESCE(timestamp_start, updated_at) DESC LIMIT ?`
  - If `identity` is provided: add
    `WHERE (human_email = ? OR source_identity = ?)` clause. Both params
    bound to the same identity value. This satisfies R1.3 — `--identity`
    matches by email or channel key.
  - If `project` is provided: add `WHERE project = ?` clause.
  - Role filtering (when `caller_role` is set):
    - `admin`: no additional filter (R3.1).
    - `member`: add `WHERE (human_email = ? OR visibility = 'shared')` using
      caller_email. This mirrors `_filter_sessions_by_role` in
      `sessions_routes.py` line 100 — members see own sessions plus sessions
      marked shared (R3.2).
    - `customer`: add `WHERE human_email = ?` using the caller identity
      resolved from terminal auth or daemon principal (R3.3).
    - When `caller_role` is None: no filter (R3.5 — unauth preserves existing
      behavior).
- Returns `list[MirrorRecord]` populated from rows, including summary,
  human_email, and visibility.

- New helper `_apply_role_filter(clauses, params, caller_email, caller_role)` to
  encapsulate the role-based WHERE clause logic — reused by search_mirrors and
  get_mirror in Task 6.

**Verification:**

- `list_mirrors()` returns mirrors ordered by recency.
- With `caller_role="member"` + `caller_email="alice@x.com"`: mirrors where
  `human_email="alice@x.com"` OR `visibility="shared"` are returned.
  → Xfail spec:
  `tests/unit/mirrors/test_store.py::TestHistoryRoleAwareSpecs::test_get_mirror_allows_member_owned_or_shared_records`
- With `caller_role="customer"` + `caller_email="bob@x.com"`: only mirrors with
  `human_email="bob@x.com"` are returned.
- With `identity="carol@x.com"`: mirrors where `human_email="carol@x.com"` OR
  `source_identity="carol@x.com"` returned.
  → Xfail spec:
  `tests/unit/mirrors/test_store.py::TestHistoryRoleAwareSpecs::test_list_mirrors_matches_source_identity_or_human_email`
- With `project="my-project"`: only mirrors in that project.

**Satisfies:** R1.5 (reads from mirrors table), R1.3 (identity filter covers
source_identity), R3.1 (admin unfiltered), R3.2 (member: own + shared), R3.3
(customer: resolved CLI identity), R3.5 (unauthenticated unfiltered), R3.6
(filtering at query time in store layer).

---

### Task 6: Apply role filtering to `search_mirrors` and `get_mirror` [x]

**What:** Add `caller_email` and `caller_role` parameters to `search_mirrors`
and `get_mirror`, using the same `_apply_role_filter` helper from Task 5.

**Why:** R3 requires all history commands (list, search, show) to apply role
filtering. Search uses `search_mirrors` and show uses `get_mirror`. The filter
must be consistent across all three commands (R3.6). The same `source_identity`
matching used in Task 5 must apply here so customers can access their own
channel-identity sessions via search and show (R3.3).

**Changes in `teleclaude/mirrors/store.py`:**

- Add `caller_email: str | None = None` and `caller_role: str | None = None`
  params to `search_mirrors`. Apply `_apply_role_filter` to the WHERE clauses.
- Add `caller_email: str | None = None` and `caller_role: str | None = None`
  params to `get_mirror`. Apply `_apply_role_filter` to the WHERE clauses.
- Both functions: when caller_role is None, no filtering (backward compat, R3.5).

**Verification:**

- `search_mirrors` with `caller_role="customer"` returns only matching mirrors
  (by resolved caller email).
- `get_mirror` with `caller_role="member"` returns shared mirrors even when the
  caller is not the owner.
- `get_mirror` with `caller_role="customer"` returns None for mirrors not owned
  by the caller.
- Both functions without caller_role work identically to current behavior.
- Makes GREEN:
  `tests/unit/mirrors/test_store.py::TestHistoryRoleAwareSpecs::test_get_mirror_allows_member_owned_or_shared_records`,
  `tests/unit/history/test_search.py::TestRoleAwareHistorySpecs::test_display_combined_history_passes_caller_context`,
  and
  `tests/unit/history/test_search.py::TestShowTranscript::test_show_transcript_passes_caller_context_to_get_mirror`.

**Satisfies:** R3.1–R3.6 for search and show commands.

---

### Task 7: `_handle_history_list` CLI handler [x]

**What:** New handler function for `telec history list` that parses flags,
resolves caller identity, queries mirrors, and formats tabular output.

**Why:** R1.1–R1.6 define the new command. This is the progressive-disclosure
entry point where agents read summaries before drilling into full transcripts.

**Changes in `teleclaude/cli/telec/handlers/history.py`:**

- New `_handle_history_list(args: list[str]) -> None` function.
- Parse flags (following the existing pattern in `_handle_history_search`):
  - `--identity <email_or_key>`: filter by human identity (email or
    source_identity key). Passed directly to `list_mirrors(identity=...)`,
    which matches by both `human_email` and `source_identity` (R1.3).
  - `--project <name>`: filter by project.
  - `--limit <n>` (default 20): max results.
- Add `_resolve_history_caller_context()` in
  `teleclaude/cli/telec/handlers/history.py` that:
  - calls `resolve_cli_caller_role()` for the effective role,
  - reads terminal email via `read_current_session_email()`, and
  - when a daemon session token exists, calls `TelecAPIClient.get_auth_whoami()`
    and normalizes a `human:<email>` principal into a fallback caller email.
- Call `list_mirrors(limit=limit, project=project, identity=identity,
caller_email=email, caller_role=role)`.
- Format output as a tabular summary per session (R1.2):
  `session_id | title | timestamp_start | timestamp_end | origin_channel |
summary | message_count`. Ordered by recency (R1.2).
- Summary display: use `summary` field; fall back to truncated title when no
  summary exists (R4.4).
- Add `_handle_history_list` to the module's `__all__`.
- Update `_handle_history` dispatcher: add `elif subcommand == "list":
_handle_history_list(args[1:])`.

**Verification:**

- `telec history list` returns tabular session summaries.
- `telec history list --identity alice@x.com` filters by identity (email or
  source_identity key, R1.3).
- `telec history list --project my-proj` filters by project (R1.4).
- `telec history list --limit 5` limits results.
- Unknown flags produce error + usage.
- Makes GREEN:
  `tests/unit/cli/telec/handlers/test_history.py::test_handle_history_list_parses_filters_and_delegates`.

**Satisfies:** R1.1 (flags), R1.2 (tabular output, ordered by recency), R1.3
(identity filter — email or source_identity key), R1.4 (project filter), R1.5
(reads mirrors), R1.6 (CLI registration).

---

### Task 8: CLI surface registration for `list` subcommand [x]

**What:** Register the `list` subcommand in the CLI surface definition so it
appears in help text and is properly routed.

**Why:** R1.6 requires the command to be registered in the CLI surface following
the existing pattern for `search` and `show`. This drives help text generation
and is referenced in the agent system prompt.

**Changes in `teleclaude/cli/telec/surface.py`:**

- Add `"list"` subcommand to the `"history"` `CommandDef.subcommands` dict,
  before `"search"`:
  ```python
  "list": CommandDef(
      desc="List session summaries from mirrors",
      flags=[
          _H,
          Flag("--identity", desc="Filter by human identity (email or key)"),
          Flag("--project", desc="Filter by project name"),
          Flag("--limit", desc="Max results (default: 20)"),
      ],
      auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
  ),
  ```
- Auth level: `_HR_ALL` because customers need to see their own history.
  The role-based filtering in the store layer ensures they only see their own
  sessions.

**Verification:**

- `telec history list --help` prints correct usage with all flags.
- `telec history --help` shows the `list` subcommand.
- Auth level allows customer, member, and admin access.

**Satisfies:** R1.6 (CLI surface registration).

---

### Task 9: Pass caller identity through search and show commands [x]

**What:** Update `_handle_history_search` and `_handle_history_show` to resolve
caller identity and pass it to the store functions for role-based filtering.

**Why:** R3 requires all history commands to apply role filtering. Without this
change, search and show would bypass the filtering added in Task 6. The identity
resolution uses the same `resolve_cli_caller_role()` mechanism (R3.4).

**Changes in `teleclaude/cli/telec/handlers/history.py`:**

- In `_handle_history_search`: before calling `display_combined_history`, call
  `_resolve_history_caller_context()` and pass `caller_email` and `caller_role`
  to the search function.
- In `teleclaude/history/search.py`: update `display_combined_history` signature
  to accept `caller_email` and `caller_role` and pass them to `search_mirrors`.
  Update `show_transcript` signature similarly and pass to `get_mirror`.
- In `_handle_history_show`: same resolution, pass to `show_transcript`.

**Verification:**

- `telec history search` as admin: sees all results.
- `telec history search` as customer: sees only own sessions (by resolved CLI
  identity).
- `telec history show` as customer for another user's session: returns not found.
- `telec history show` without auth: works as before (R3.5).
- Makes GREEN:
  `tests/unit/history/test_search.py::TestRoleAwareHistorySpecs::test_display_combined_history_passes_caller_context`
  and
  `tests/unit/history/test_search.py::TestShowTranscript::test_show_transcript_passes_caller_context_to_get_mirror`.

**Satisfies:** R3.1–R3.5 for search and show commands, R3.4 (uses
resolve_cli_caller_role).

---

### Task 10: Update `demo.md` [x]

**What:** Update `todos/history-role-aware/demo.md` to reflect the corrected
member access semantics and the source_identity identity filter scope.

**Why:** The demo is a mandatory review lane artifact. The guided presentation
(Step 2) currently describes member access as "sees only their own sessions" —
this contradicts R3.2 (members see own + shared). The demo must reflect the
actual implementation so the reviewer can validate the shipped behavior. Without
this task, the demo artifact would be stale at review time.

**Changes in `todos/history-role-aware/demo.md`:**

- In the Guided Presentation Step 2 ("Role-based filtering"), update the member
  bullet:
  - Before: "Member: sees only their own sessions."
  - After: "Member: sees own sessions plus sessions with `visibility='shared'`
    (mirrors the sessions API pattern in `_filter_sessions_by_role`)."
- Update the identity filter description to note that `--identity` matches by
  `human_email` OR `source_identity`, covering both email and channel key.

**Verification:**

- `demo.md` Step 2 accurately describes the member access behavior implemented
  in Task 5.
- `demo.md` identity filter description matches the `WHERE (human_email = ? OR
source_identity = ?)` clause.

**Satisfies:** Demo lane coverage for the new CLI command and changed auth
behavior (DoD § Documentation).

---

### Task 11: Update CLI documentation [x]

**What:** Update the CLI tool spec for `telec history list` so the documented
surface matches the shipped command.

**Why:** The DoD documentation gate requires relevant CLI docs to reflect new
subcommands. The grounded documentation source already present in this repo is
`docs/global/general/spec/tools/telec-cli.md`, not a non-existent local
`AGENTS.md`.

**Changes:**

- In `docs/global/general/spec/tools/telec-cli.md`, update the `telec history`
  section to include the `list` subcommand alongside `search` and `show`,
  including `--identity`, `--project`, and `--limit`.

**Verification:**

- The `telec history` section in
  `docs/global/general/spec/tools/telec-cli.md` includes `list`.
- The flag descriptions for `--identity`, `--project`, and `--limit` are
  accurate.

**Satisfies:** DoD § Documentation (relevant CLI docs updated for new
subcommand).

---

## Task Dependency Order

```
Task 1 (migration)
  └→ Task 2 (dataclass + SQL)
       ├→ Task 3 (channel metadata + human_email + visibility flow)
       │    └→ Task 4 (summary generation)
       ├→ Task 5 (list_mirrors store function)
       │    └→ Task 6 (role filtering on search/get)
       │         └→ Task 9 (pass identity through CLI)
       └→ Task 7 (list CLI handler)
            └→ Task 8 (surface registration)
                 ├→ Task 10 (update demo.md)
                 └→ Task 11 (update docs)
```

Tasks 3–4 and 5–6 can proceed in parallel after Task 2. Task 7 depends on
Task 5 (uses list_mirrors). Task 9 depends on Task 6 (uses updated search/get
signatures). Tasks 10 and 11 depend on Task 8 (surface is finalized).

## Referenced Files

### Modified

- `teleclaude/mirrors/store.py` — MirrorRecord, SessionMirrorContext, upsert,
  get, search, new list_mirrors
- `teleclaude/mirrors/generator.py` — channel metadata, human_email, visibility,
  summary generation, \_extract_channel_identifiers
- `teleclaude/mirrors/processors.py` — pass context fields to generator
- `teleclaude/cli/telec/handlers/history.py` — new list handler, identity
  resolution for search/show
- `teleclaude/cli/telec/surface.py` — register list subcommand
- `teleclaude/history/search.py` — accept caller identity params
- `tests/unit/mirrors/test_store.py` — xfail specs + tests for list_mirrors,
  role filtering
- `tests/unit/mirrors/test_generator.py` — xfail specs for channel metadata
- `tests/unit/mirrors/test_processors.py` — xfail specs for expanded context flow
- `tests/unit/history/test_search.py` — xfail specs for caller-context passthrough
- `tests/unit/cli/telec/handlers/test_history.py` — xfail specs for list handler
- `docs/global/general/spec/tools/telec-cli.md` — CLI surface documentation for
  `telec history`
- `todos/history-role-aware/demo.md` — corrected member/identity descriptions

### Created

- `teleclaude/core/migrations/033_add_mirror_summary_and_human_email.py`

### Read-only (patterns/reference)

- `teleclaude/core/summarizer.py` — existing summarizer pattern
- `teleclaude/cli/session_auth.py` — resolve_cli_caller_role()
- `teleclaude/core/identity.py` — IdentityResolver, IdentityContext
- `teleclaude/core/models/_adapter.py` — SessionAdapterMetadata
- `teleclaude/core/models/_session.py` — Session.human_email, Session.visibility
- `teleclaude/api/session_access.py` — existing role filtering pattern
- `teleclaude/api/sessions_routes.py` — \_filter_sessions_by_role pattern
  (line 100: member sees own + shared)
- `teleclaude/core/migrations/028_add_mirror_source_identity.py` — migration
  pattern for table rebuild
