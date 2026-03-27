# Implementation Plan: identity-origin-cleanup

## Overview

Eliminate `channel_metadata` as a property from commands and metadata. After this work,
edges construct typed origin metadata objects directly and pass them via `origin_metadata`
on the command. Internal routing fields use first-class command fields exclusively.
`working_slug` is derived from subdir. Daemon headless session creation uses the
command pipeline.

The approach is bottom-up: add typed metadata types first (standalone), then remove the
`channel_metadata` property from commands and add `origin_metadata`, then update edges to
construct typed origin metadata, then update the session handler and command mapper,
then clean the API routes, then refactor the daemon, then verify elimination. Each task
makes a specific set of xfail test specs GREEN.

## Task Order

Tasks are ordered by dependency: typed metadata first (standalone), then field removal
(core), then caller cleanup (edges), then handler derivation and fallback removal, then
daemon refactor, then documentation.

**Sequencing constraint for Tasks 4, 5, 6:** These tasks must be applied in the order
6 → 5 → 4 (API routes first, mapper second, handler last). The handler fallback removal
in Task 4 must happen after the routes (Task 6) and mapper (Task 5) are updated to pass
`initiator_session_id` through first-class fields. Applying Task 4 before Task 6 creates
a window where `initiator_session_id` is lost for API-originated sessions.

---

### Task 1: Add WebOriginMetadata and TerminalOriginMetadata dataclasses [x]

**What:** Add two new dataclasses to `teleclaude/core/models/_adapter.py` following the
existing `TelegramAdapterMetadata` pattern — `from_dict`/`to_dict`, typed fields,
`asdict_exclude_none` serialization.

**Why:** R4 requires typed schemas for web and terminal origin metadata. The identity
resolver must accept these typed instances. Creating the types first is a zero-risk
standalone change that unblocks R4 resolver wiring and the email routing changes in
later tasks.

Each dataclass must implement the `Mapping[str, object]` protocol (`__getitem__`,
`__len__`, `__iter__`, `get`) so the resolver's existing `channel_metadata.get("email")`
call works unchanged when passed a typed instance. This avoids changing the resolver
signature or duplicating resolution logic.

**Fields:**

- `WebOriginMetadata`: `email: str | None = None`
- `TerminalOriginMetadata`: `email: str | None = None`

Both follow the `from_dict`/`to_dict` pattern and `asdict_exclude_none`.

**Verification:** Remove xfail markers from `tests/unit/core/models/test_typed_origin_metadata.py`.
Tests `TestWebOriginMetadata` (4 tests) and `TestTerminalOriginMetadata` (4 tests) go GREEN.

**Files:** `teleclaude/core/models/_adapter.py`

---

### Task 2: Wire typed origin metadata into IdentityResolver.resolve() [x]

**What:** Verify that `IdentityResolver.resolve()` accepts typed metadata instances
alongside raw dicts. Since the typed dataclasses from Task 1 implement `Mapping`,
the resolver's existing `.get("email")` calls work without code changes. The type
annotation `Mapping[str, object]` already accommodates both paths. If the Mapping
implementation is correct, this task is verification-only.

**Why:** R4 requires the identity resolver to read from typed schemas. The Mapping
protocol on the typed metadata is the bridge — it lets the resolver work with both
raw dicts and typed objects through the same `.get()` interface.

**Verification:** Remove xfail markers from `TestIdentityResolverReadsTypedMetadata`
in `tests/unit/core/models/test_typed_origin_metadata.py`. Both tests go GREEN.

**Files:** `teleclaude/core/identity.py` (verify type annotation; no code change
expected if Mapping protocol is correct)

---

### Task 3: Remove working_slug from CreateSessionCommand [x]

**What:** Remove the `working_slug` field, parameter, and assignment from
`CreateSessionCommand.__init__` and the class-level field declaration.

**Why:** R1 requires working_slug to be derived, not passed. Removing it from the
command model is the first step — callers that pass it will get TypeError, which
the tests assert. This change cascades: any caller still passing working_slug
will fail at the type level.

**Verification:** Remove xfail markers from `TestCreateSessionCommandFieldRemoval`
in `tests/unit/core/test_working_slug_derivation.py`. Both tests go GREEN.

**Files:** `teleclaude/types/commands.py`

---

### Task 4: Derive working_slug in session handler, remove fallback block [x]

**What:** In `teleclaude/core/command_handlers/_session.py`, `create_session()`:

1. **Add derivation logic:** After determining `subfolder` from `cmd.subdir`, derive
   `working_slug` from the `trees/{slug}` pattern:
   - If `subfolder` starts with `trees/`, extract the slug portion after the prefix
   - Otherwise, set `working_slug = None`

2. **Delete the channel_metadata fallback block** (around line 117-123) that reads
   `subfolder`, `working_slug`, and `initiator_session_id` from `cmd.channel_metadata`.
   This block will not compile after Task 6 removes `channel_metadata` from the command,
   so it must be removed. After this:
   - `subfolder` comes only from `cmd.subdir`
   - `working_slug` comes from derivation only
   - `initiator_session_id` comes from `cmd.initiator_session_id` only

3. **Update identity resolution** (around line 133-137) to read from `cmd.origin_metadata`
   instead of `cmd.channel_metadata`:
   - `if cmd.origin_metadata: identity = get_identity_resolver().resolve(origin, cmd.origin_metadata)`

**Why:** R1 requires derivation instead of explicit passing. R2 requires the property
elimination. The handler is the central consumer — it must switch from `channel_metadata`
to `origin_metadata` for identity resolution and from derivation for `working_slug`.

**Verification:** Remove xfail markers from:

- `TestWorkingSlugDerivation` in `test_working_slug_derivation.py` (3 tests) → GREEN

**Files:** `teleclaude/core/command_handlers/_session.py`

---

### Task 5: Clean command mapper — remove `channel_metadata` handling [x]

**What:** In `teleclaude/core/command_mapper.py`:

1. **Telegram mapper (`map_telegram_input`):** Remove `working_slug` and
   `initiator_session_id` extraction from `metadata.channel_metadata` in the
   `new_session` branch (around line 125-131). `CreateSessionCommand` no longer
   has `working_slug` (Task 3) or `channel_metadata` (Task 6). The mapper
   constructs typed origin metadata from the Telegram-specific fields on the
   metadata and passes it via `origin_metadata` on the command.

2. **API mapper (`map_api_input`):** For `new_session`, extract
   `initiator_session_id` from the payload dict directly and set it on the
   CreateSessionCommand. No `channel_metadata` to handle — `origin_metadata` comes
   from the API route (Task 6).

3. **Redis mapper (`map_redis_input`):** Remove `channel_metadata` passthrough.
   Origin data comes from the typed metadata objects on the parsed message.

4. **Rename `_extract_actor_from_channel_metadata`** to `_extract_actor` since
   it no longer reads from `channel_metadata`. Actor context comes from named
   fields on `MessageMetadata` (Task 7).

**Why:** R1 and R2 require the command mapper to build commands from first-class
fields and typed origin metadata only. `channel_metadata` no longer exists as a
property on commands.

**Verification:** Remove xfail markers from:

- `TestCommandMapperNoWorkingSlugExtraction` in `test_working_slug_derivation.py` (2 tests) → GREEN
- `TestCommandMapperNoInternalFieldInjection` in `test_channel_metadata_cleanup.py` (2 tests) → GREEN

**Files:** `teleclaude/core/command_mapper.py`

---

### Task 6: Remove `channel_metadata` from commands, add `origin_metadata`, update API routes [x]

**What:**

1. **Remove `channel_metadata` from `CreateSessionCommand`** in `teleclaude/types/commands.py`:
   - Delete the `channel_metadata` field, parameter, and assignment
   - Add a new `origin_metadata` field typed as the union of typed origin metadata objects
     (`TelegramOriginMetadata | DiscordOriginMetadata | WhatsAppOriginMetadata | WebOriginMetadata | TerminalOriginMetadata | None`)
   - This is the replacement: edges pass typed origin metadata via `origin_metadata`

2. **Remove `channel_metadata` from `MessageMetadata`** in `teleclaude/core/models/_snapshot.py`
   and `teleclaude/core/models/_session.py`:
   - Delete the `channel_metadata` field from both models
   - Actor context for cross-computer messaging moves to named fields (see Task 7)

3. **Update `teleclaude/api/sessions_actions_routes.py` (`_prepare_run_session`):**
   - Stop building `channel_metadata` dicts entirely
   - Pass `initiator_session_id` as a first-class field on `RunSessionPlan` → CreateSessionCommand
   - For direct web/terminal sessions (no initiator), construct
     `WebOriginMetadata(email=caller_email)` or `TerminalOriginMetadata(email=caller_email)`
     and pass via `origin_metadata`
   - For child sessions with an initiator, identity inherits via `initiator_session_id` — no
     origin_metadata needed

4. **Update `teleclaude/api/sessions_routes.py`:**
   - Remove `_build_channel_metadata()` function entirely
   - Pass `initiator_session_id` in the API payload for `map_api_input`
   - For direct web/terminal sessions, construct typed origin metadata and pass via `origin_metadata`

5. **Update `teleclaude/core/command_mapper.py`:**
   - All mappers (`map_telegram_input`, `map_api_input`, `map_redis_input`) stop reading/writing
     `channel_metadata` on commands
   - `map_api_input` reads `initiator_session_id` from the payload dict directly
   - Actor extraction (`_extract_actor_from_channel_metadata`) is renamed and reads from
     the typed origin metadata or named fields instead

**Why:** R2 requires elimination of `channel_metadata` as a property. This task is the
central structural change — it removes the property, adds the typed replacement, and
updates all internal callers (API routes, command mapper). Edge adapters are updated in
Task 6b.

**Verification:** Remove xfail markers from:

- `TestCallerSiteWorkingSlugRemoval` in `test_working_slug_derivation.py` (1 test) → GREEN
- `TestChannelMetadataPropertyRemoved` in `test_channel_metadata_cleanup.py` → GREEN
- `TestCommandMapperNoInternalFieldInjection` in `test_channel_metadata_cleanup.py` (2 tests) → GREEN

**Files:** `teleclaude/types/commands.py`, `teleclaude/core/models/_snapshot.py`,
`teleclaude/core/models/_session.py`, `teleclaude/api/sessions_actions_routes.py`,
`teleclaude/api/sessions_routes.py`, `teleclaude/core/command_mapper.py`

---

### Task 6b: Convert edge adapters from `channel_metadata` dicts to typed origin metadata [partial]

**What:** Every edge adapter that currently constructs `channel_metadata` dicts must
instead construct typed origin metadata objects and pass them via `origin_metadata` on the
command (for session creation) or via `MessageMetadata` named fields (for messages).

1. **Telegram** (`teleclaude/adapters/telegram/input_handlers.py`, `command_handlers.py`,
   `callback_handlers.py`, `private_handlers.py`):
   - Currently builds `channel_metadata = {"message_id": ..., "user_id": ..., "user_name": ...}`
   - Construct `TelegramOriginMetadata(user_id=..., user_name=...)` instead
   - `message_id` is per-message context, not identity — moves to a named field on
     `MessageMetadata` or is passed as a separate parameter

2. **Discord** (`teleclaude/adapters/discord/input_handlers.py`, `gateway_handlers.py`):
   - Currently builds `channel_metadata = {"user_id": ..., "discord_user_id": ..., "platform": "discord"}`
   - Construct `DiscordOriginMetadata(user_id=..., discord_user_id=...)` instead

3. **WhatsApp** (`teleclaude/hooks/whatsapp_handler.py`):
   - Currently builds `channel_metadata = {"phone_number": ..., "message_id": ...}`
   - Construct `WhatsAppOriginMetadata(phone_number=...)` instead
   - `message_id` moves to a named field on `MessageMetadata`

4. **Update session handler** (`teleclaude/core/command_handlers/_session.py`):
   - Read identity signals from `cmd.origin_metadata` instead of `cmd.channel_metadata`
   - Pass `cmd.origin_metadata` to `get_identity_resolver().resolve(origin, cmd.origin_metadata)`
   - Merge `cmd.origin_metadata` onto `origin_metadata` via `db.update_origin_metadata()`

**Why:** R2 requires edges to construct typed origin metadata directly — no intermediate
dict. This task converts every edge adapter to the new pattern. The typed objects
implement `Mapping[str, object]` (Task 1), so the identity resolver works unchanged.

**Verification:** Remove xfail markers from:

- `TestSessionHandlerNoChannelMetadataFallback` in `test_channel_metadata_cleanup.py` (3 tests) → GREEN
- `TestChannelMetadataEdgeOnly` in `test_channel_metadata_cleanup.py` (1 test) → GREEN

**Files:** `teleclaude/adapters/telegram/input_handlers.py`,
`teleclaude/adapters/telegram/command_handlers.py`,
`teleclaude/adapters/telegram/callback_handlers.py`,
`teleclaude/adapters/telegram/private_handlers.py`,
`teleclaude/adapters/discord/input_handlers.py`,
`teleclaude/adapters/discord/gateway_handlers.py`,
`teleclaude/hooks/whatsapp_handler.py`,
`teleclaude/core/command_handlers/_session.py`

---

### Task 7: Promote target_computer and actor context to named fields

**What:**

1. **Redis transport** (`teleclaude/transport/redis_transport/_messaging.py`):
   - Remove the lines (around 248-250) that inject `target_computer` into
     `metadata.channel_metadata`
   - Route `parsed.initiator` through the existing `RedisTransportMetadata.target_computer`
     field instead
   - Remove any `channel_metadata` reads/writes in `_request_response.py` (lines 126-127
     serialize `metadata.channel_metadata` — this path must be updated or removed since
     the property no longer exists)

2. **Fanout coordinator** (`teleclaude/core/agent_coordinator/_fanout.py`):
   - Remove the `channel_metadata` dict at line 330-336 that carries actor context:
     ```
     channel_metadata={
         "actor_id": actor_id,
         "actor_name": actor_name,
         "actor_role": "system",
         "actor_agent": "system",
         "actor_computer": sender_computer,
     }
     ```
   - Add named fields to `MessageMetadata` for actor context: `actor_id`, `actor_name`,
     `actor_role`, `actor_agent`, `actor_computer` (or a dedicated `ActorContext` dataclass)
   - Update the fanout coordinator to pass actor context via these named fields

3. **Redis transport serialization** (`_request_response.py`):
   - Update message serialization to carry actor context via the new named fields
     instead of `channel_metadata` JSON blob

**Why:** R3 requires target_computer and actor context fields to use named fields.
`channel_metadata` no longer exists as a property, so all fields that were smuggled
through it must have proper homes.

**Verification:** Remove xfail markers from `TestTargetComputerNotInChannelMetadata`
in `tests/unit/transport/redis_transport/test_target_computer_named_field.py`
(3 tests) → GREEN.

**Files:** `teleclaude/transport/redis_transport/_messaging.py`,
`teleclaude/transport/redis_transport/_request_response.py`,
`teleclaude/core/agent_coordinator/_fanout.py`,
`teleclaude/core/models/_snapshot.py`

---

### Task 8: Refactor daemon headless session creation via command pipeline

**What:** In `teleclaude/daemon_hook_outbox.py`, `_ensure_headless_session()`:

1. Replace the `db.create_headless_session()` call with constructing a
   `CreateSessionCommand` and routing it through the command service
   (`get_command_service().execute()`).
2. Remove the `get_identity_resolver().resolve_from_terminal()` call. Identity
   for headless sessions flows through the session handler: if the hook event
   carries enough context to identify a parent session, pass `initiator_session_id`
   on the command and identity inherits from the parent. For standalone hooks with
   no parent, set `system_role` on the command to bypass identity resolution
   (system-role sessions are trusted internal principals).
3. Populate the CreateSessionCommand with the same fields currently passed to
   `db.create_headless_session()`: session_id, computer_name (via config),
   origin, title, active_agent, native_session_id, native_log_file, project_path,
   subdir.

**Why:** R6 requires daemon headless session creation to go through the command
pipeline. Direct DB calls bypass identity resolution, metadata normalization, and
event emission. `resolve_from_terminal()` is a TTY-dependent method that doesn't
work in daemon context — it reads the local terminal's logged-in email, which is
irrelevant for a background daemon process.

**Verification:** Remove xfail markers from `TestDaemonHeadlessViaCommandPipeline`
in `tests/unit/test_daemon_headless_pipeline.py` (2 tests) → GREEN.

**Files:** `teleclaude/daemon_hook_outbox.py`

---

### Task 9: Remove resolve_from_terminal and update CLI callers

**What:**

1. **Remove `resolve_from_terminal()`** from `IdentityResolver` in
   `teleclaude/core/identity.py`.

2. **Update CLI callers** that currently call `resolve_from_terminal()`:
   - `teleclaude/cli/telec/handlers/docs.py` (lines 78, 114): Replace with a
     call that reads the terminal email via `read_current_session_email()` and
     routes it through the standard resolver — either
     `resolve("terminal", TerminalOriginMetadata(email=...))` or
     `resolve_by_email(read_current_session_email() or "")`.

   - `teleclaude/cli/config_cli.py` (line 63): Same replacement pattern.

   - `teleclaude/cli/cartridge_cli.py` (line 55): Same replacement pattern.

**Why:** R6 requires `resolve_from_terminal()` removal. The method is a shortcut
that couples identity resolution to TTY state via a hidden side-channel.
CLI callers should use the standard `resolve()` or `resolve_by_email()` path,
reading the session email from `read_current_session_email()` explicitly.
This makes the identity source visible in the call chain.

**Verification:** Remove xfail markers from:

- `TestResolveFromTerminalRemoved` in `test_daemon_headless_pipeline.py` (1 test) → GREEN
- `TestCliCallersAlternativePath` in `test_daemon_headless_pipeline.py` (3 tests) → GREEN

**Files:** `teleclaude/core/identity.py`, `teleclaude/cli/telec/handlers/docs.py`,
`teleclaude/cli/config_cli.py`, `teleclaude/cli/cartridge_cli.py`

---

### Task 10: Verify `channel_metadata` elimination and final cleanup

**What:**

1. Verify that `channel_metadata` as a property does not exist on `CreateSessionCommand`,
   `ProcessMessageCommand`, `MessageMetadata`, or any command/metadata type.

2. Verify no production code (outside `RedisTransportMetadata`) references `channel_metadata`
   as a property on commands or metadata. Scan for patterns like `.channel_metadata`,
   `channel_metadata=`, `["channel_metadata"]` in production code paths.

3. Add a comment to `RedisTransportMetadata.channel_metadata` (the JSON string for Redis
   wire format) clarifying it is transport serialization only — not the eliminated semantic
   property.

4. Run pre-commit hooks to verify all tests pass, all xfail markers are removed,
   and no lint/type errors remain.

**Why:** R5 requires verification that `channel_metadata` is fully eliminated as a
semantic concept from commands and metadata. The only surviving usage is
`RedisTransportMetadata.channel_metadata` which is transport-level serialization.

**Verification:** All tests green. Pre-commit hooks pass. No remaining xfail markers
in the spec test files. `grep -r "channel_metadata" teleclaude/` returns only
`RedisTransportMetadata` and its serialization path.

**Files:** `teleclaude/core/models/_adapter.py` (comment on RedisTransportMetadata)

---

## Requirement → Task Traceability

| Requirement                          | Tasks       | Test Spec File                        |
| ------------------------------------ | ----------- | ------------------------------------- |
| R1 (working_slug)                    | 3, 4, 5, 6  | `test_working_slug_derivation.py`     |
| R2 (eliminate channel_metadata)      | 4, 5, 6, 6b | `test_channel_metadata_cleanup.py`    |
| R3 (actor context + target_computer) | 7           | `test_target_computer_named_field.py` |
| R4 (typed metadata)                  | 1, 2        | `test_typed_origin_metadata.py`       |
| R5 (verify elimination)              | 10          | `test_channel_metadata_cleanup.py`    |
| R6 (daemon pipeline)                 | 8, 9        | `test_daemon_headless_pipeline.py`    |

## Referenced Files (production)

- `teleclaude/core/models/_adapter.py`
- `teleclaude/core/models/_snapshot.py`
- `teleclaude/core/models/_session.py`
- `teleclaude/core/identity.py`
- `teleclaude/types/commands.py`
- `teleclaude/core/command_handlers/_session.py`
- `teleclaude/core/command_mapper.py`
- `teleclaude/api/sessions_actions_routes.py`
- `teleclaude/api/sessions_routes.py`
- `teleclaude/transport/redis_transport/_messaging.py`
- `teleclaude/transport/redis_transport/_request_response.py`
- `teleclaude/core/agent_coordinator/_fanout.py`
- `teleclaude/adapters/telegram/input_handlers.py`
- `teleclaude/adapters/telegram/command_handlers.py`
- `teleclaude/adapters/telegram/callback_handlers.py`
- `teleclaude/adapters/telegram/private_handlers.py`
- `teleclaude/adapters/discord/input_handlers.py`
- `teleclaude/adapters/discord/gateway_handlers.py`
- `teleclaude/hooks/whatsapp_handler.py`
- `teleclaude/daemon_hook_outbox.py`
- `teleclaude/cli/telec/handlers/docs.py`
- `teleclaude/cli/config_cli.py`
- `teleclaude/cli/cartridge_cli.py`

## Referenced Files (test specs)

- `tests/unit/core/test_working_slug_derivation.py`
- `tests/unit/core/test_channel_metadata_cleanup.py`
- `tests/unit/transport/redis_transport/test_target_computer_named_field.py`
- `tests/unit/core/models/test_typed_origin_metadata.py`
- `tests/unit/test_daemon_headless_pipeline.py`
