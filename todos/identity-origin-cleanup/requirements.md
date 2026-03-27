# Requirements: identity-origin-cleanup

## Goal

Eliminate `channel_metadata` as a concept and property. After this work:

- The `channel_metadata` property does not exist on `CreateSessionCommand` or `MessageMetadata`
- Edges construct typed origin metadata objects directly (`TelegramOriginMetadata`, `DiscordOriginMetadata`, `WhatsAppOriginMetadata`, `WebOriginMetadata`, `TerminalOriginMetadata`) and pass them via an `origin_data` field on the command
- The session handler merges typed origin metadata onto the session's `origin_metadata` under the platform key
- The identity resolver reads from typed origin metadata objects, not loose dicts
- Internal routing fields (`initiator_session_id`, `working_slug`, `subfolder`, `email`) use first-class command fields exclusively
- `working_slug` is derived from the `subdir` convention (`trees/{slug}`) rather than passed explicitly
- Daemon headless session creation uses the command pipeline instead of bypassing it

Phase 1 (identity resolver returning empty instead of customer default) is already delivered (commit `23fddb1d8`).

## Scope

### In scope

- Phases 2–6 as described in the input
- Removal of `channel_metadata` property from `CreateSessionCommand` and `MessageMetadata`
- All edge adapters (Telegram, Discord, WhatsApp, web, terminal) updated to construct typed origin metadata objects instead of `channel_metadata` dicts
- All call sites that construct, pass, or read `working_slug`
- Actor context fields (`actor_id`, `actor_name`, `actor_role`, `actor_agent`, `actor_computer`) promoted to named fields
- Typed origin metadata dataclasses for web and terminal origins (the only two missing)
- Daemon headless session creation refactored through the command pipeline
- Removal of `resolve_from_terminal()` from the identity resolver

### Out of scope

- Changes to the existing per-platform adapter metadata types (`TelegramAdapterMetadata`, `DiscordAdapterMetadata`, etc.) — these are adapter-specific DB-persisted metadata, distinct from origin metadata
- Database schema migrations (the `working_slug` column on the sessions table remains; it becomes derived-and-stored rather than passed-and-stored) [inferred]
- Changes to the `IdentityResolver.resolve()` method's platform resolution logic beyond accepting typed origin metadata [inferred]
- `RedisTransportMetadata.channel_metadata` (JSON string for Redis wire format) — this is transport serialization, not the semantic property being eliminated; may be renamed for clarity but is not blocking [inferred]

## Requirements

### R1: Remove explicit `working_slug` passing

`working_slug` must be derived from the `subdir` field using the established `trees/{slug}` convention rather than passed as an explicit parameter through the session creation chain.

**Success criteria:**

- `working_slug` field is removed from `CreateSessionCommand`
- All callers that currently set `working_slug` on the command or inject it into `channel_metadata` no longer do so
- The session creation handler derives `working_slug` from `subdir` when `subdir` matches the `trees/{slug}` pattern
- Sessions created with a `subdir` of `trees/my-slug` have `working_slug` set to `my-slug` in the database
- Sessions created without a matching `subdir` have `working_slug` set to `None`
- The `command_mapper` no longer extracts `working_slug` from `channel_metadata`

### R2: Eliminate `channel_metadata` property from commands

The `channel_metadata` property is removed from `CreateSessionCommand` and from `MessageMetadata` on `ProcessMessageCommand`. There is no intermediate dict. Edges construct typed origin metadata objects directly and pass them via a new `origin_data` field on the command.

**Success criteria:**

- `channel_metadata` field does not exist on `CreateSessionCommand`
- `channel_metadata` field does not exist on `MessageMetadata` (the per-message metadata used by `ProcessMessageCommand`, `HandleVoiceCommand`, etc.)
- A new `origin_data` field on `CreateSessionCommand` accepts a typed origin metadata object (`TelegramOriginMetadata | DiscordOriginMetadata | WhatsAppOriginMetadata | WebOriginMetadata | TerminalOriginMetadata | None`)
- Edge adapters that currently build `channel_metadata` dicts (Telegram `user_id`/`message_id`, Discord `user_id`/`discord_user_id`, WhatsApp `phone_number`, web `email`, terminal `email`) construct typed origin metadata objects instead
- The session creation handler reads identity signals from the typed `origin_data` object, not from a loose dict
- The session creation handler merges `origin_data` onto the session's `origin_metadata` under the platform key
- The identity resolver's `resolve()` method accepts typed origin metadata objects (they already implement `Mapping[str, object]` via Task 1/R4)
- The session handler no longer extracts `subfolder`, `working_slug`, or `initiator_session_id` from any dict — these use first-class command fields exclusively
- `CreateSessionCommand` has `initiator_session_id` and `subdir` as explicit fields (they already exist — this requirement ensures they are the sole path) [inferred]

### R3: Promote actor context and target_computer to named fields

The Redis transport messaging layer injects `target_computer` into `channel_metadata`. The fanout coordinator injects actor context fields (`actor_id`, `actor_name`, `actor_role`, `actor_agent`, `actor_computer`) into `channel_metadata` on `MessageMetadata` for cross-computer delivery. Both must use named fields since `channel_metadata` no longer exists.

**Success criteria:**

- `target_computer` is not injected into `channel_metadata` in the Redis transport messaging path; it uses the existing `RedisTransportMetadata.target_computer` field or an equivalent named path
- Actor context fields (`actor_id`, `actor_name`, `actor_role`, `actor_agent`, `actor_computer`) are not injected into `channel_metadata` in the fanout coordinator; they use named fields on `MessageMetadata` or a dedicated `ActorContext` type
- No code path constructs a `channel_metadata` dict to carry actor or transport routing fields

### R4: Typed origin metadata for web and terminal

Typed dataclasses must be added for web and terminal origin metadata, following the existing adapter metadata pattern (`from_dict`/`to_dict`, dataclass with typed fields).

**Success criteria:**

- A web origin metadata type exists with fields for the web platform's identity signals (email at minimum)
- A terminal origin metadata type exists with fields for the terminal platform's identity signals (email at minimum)
- The identity resolver can read from these typed schemas when resolving identity from `origin_metadata`
- The types follow the existing pattern established by `TelegramAdapterMetadata`, `DiscordAdapterMetadata`, `WhatsAppAdapterMetadata` [inferred]

### R5: Verify `channel_metadata` elimination

After R1–R4 remove the property and all callers, verify that `channel_metadata` as a semantic concept is fully eliminated from commands and metadata.

**Success criteria:**

- No production code references `channel_metadata` as a property on `CreateSessionCommand`, `ProcessMessageCommand`, `MessageMetadata`, or any command/metadata type
- The `command_mapper` does not read or write `channel_metadata` on any command it constructs
- The session handler does not read `channel_metadata` from any command
- `RedisTransportMetadata.channel_metadata` (the JSON string for Redis wire format) is the only surviving usage — it is transport serialization, not a semantic property, and is documented as such

### R6: Daemon headless session creation via command pipeline

The daemon's headless session creation must go through the `CreateSessionCommand` pipeline instead of calling `db.create_headless_session()` directly.

**Success criteria:**

- The daemon hook outbox constructs a `CreateSessionCommand` and routes it through the command service
- Identity propagates from the parent session (via `initiator_session_id` and the existing parent-identity-inheritance logic in the session creation handler) rather than calling `resolve_from_terminal()`
- `resolve_from_terminal()` is removed from the identity resolver
- Existing callers of `resolve_from_terminal()` (CLI docs handler, config CLI, cartridge CLI) use an alternative path that does not depend on a method being removed [inferred — these callers exist and must not break]
- The `db.create_headless_session()` method is removed or deprecated after all callers are migrated

## Constraints

- Backward compatibility: existing sessions in the database with `working_slug` set must continue to work. The column remains; only the population path changes. [inferred]
- Edge adapters must continue to deliver platform identity signals to the session handler. The mechanism changes from `channel_metadata` dicts to typed origin metadata objects, but the data must not be lost.
- `resolve_from_terminal()` has legitimate CLI callers that resolve identity for access control (docs, config, cartridge). These callers need a replacement path before the method can be removed. [inferred]
- `RedisTransportMetadata.channel_metadata` (JSON string) is transport-level serialization for cross-computer message forwarding. It survives the elimination of the semantic `channel_metadata` property but should be documented to prevent confusion. [inferred]

## Risks

- **Scope size:** This todo spans 6 phases touching ~15 files. Assessed as atomic — the phases are sequentially dependent and not independently shippable.
- **Edge adapter regression:** Converting edge adapters from `channel_metadata` dicts to typed origin metadata objects must preserve all platform identity signals. Test coverage at the session creation handler boundary is critical to verify identity resolution still works for all platforms.
- **Identity resolution regression:** Removing `resolve_from_terminal()` while CLI callers still depend on it would break terminal-based access control.
