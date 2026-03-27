# identity-origin-cleanup — Input

Identity propagation + eliminate channel_metadata + origin metadata normalization

## Problem

Child sessions spawned by daemon-created orchestrators lose human identity. The IdentityResolver.resolve() defaulted to customer when it can't identify the caller, preventing parent identity inheritance. Worker sessions get routed to the help desk in Discord.

Additionally, `channel_metadata` has grown from an edge-only concept into a grab bag carrying internal routing fields (initiator_session_id, working_slug, email). It should not exist as a property at all. There is only `origin_metadata` — each platform key holds typed metadata (`DiscordOriginMetadata`, `TelegramOriginMetadata`, `WhatsAppOriginMetadata`, `WebOriginMetadata`, `TerminalOriginMetadata`). Edges construct typed origin metadata directly and merge it onto the session's `origin_metadata` under the platform key. No intermediate dict, no `channel_metadata` property on commands or message metadata.

## Phase 1 (done)

Identity resolver returns empty IdentityContext instead of customer default. Fail fast on unidentified sessions without system_role. Commit `23fddb1d8`.

## Phase 2: Remove working_slug

Derive from subdir convention (`trees/{slug}`). Remove `working_slug` from `CreateSessionCommand`, command_mapper, session creation handler, API routes. The DB column stays but is populated from derivation, not passed explicitly.

## Phase 3: Eliminate channel_metadata as a property

Remove the `channel_metadata` property from `CreateSessionCommand` and `MessageMetadata` entirely. There is no intermediate dict. Internal routing fields (`initiator_session_id`, `subfolder`) are already first-class command fields — stop reading them from channel_metadata as fallbacks.

Edges construct typed origin metadata directly:

- Discord edge → `DiscordOriginMetadata(user_id=..., guild_id=..., platform="discord")`
- Telegram edge → `TelegramOriginMetadata(user_id=..., platform="telegram")`
- WhatsApp edge → `WhatsAppOriginMetadata(phone_number=..., platform="whatsapp")`
- Web edge → `WebOriginMetadata(email=...)`
- Terminal edge → `TerminalOriginMetadata(email=...)`

These get merged onto `origin_metadata[platform_key]` at session creation. The identity resolver reads from these typed schemas. No loose dict lookups.

## Phase 4: Add typed WebOriginMetadata and TerminalOriginMetadata

Match the existing adapter metadata pattern (from_dict/to_dict, dataclass with typed fields). These are the only two missing. The identity resolver reads email from them for web/terminal origins.

## Phase 5: Promote Redis transport fields

`target_computer` and actor context fields (`actor_id`, `actor_name`, `actor_role`, `actor_agent`, `actor_computer`) in Redis transport and agent coordinator fanout must use named fields, not channel_metadata entries (which no longer exists).

## Phase 6: Daemon headless session creation via command pipeline

Replace `db.create_headless_session()` with constructing a `CreateSessionCommand` and routing through `get_command_service().create_session()`. Remove `resolve_from_terminal()` — identity propagates from parent session via initiator_session_id and the existing inheritance logic. CLI callers of `resolve_from_terminal()` use `resolve_by_email(read_current_session_email())` instead.

## Key design decision

`channel_metadata` does not exist as a concept after this cleanup. There is only `origin_metadata` with typed platform keys. The word "channel" disappears from internal operations. Edges write typed origin metadata directly — no intermediate dict, no property on commands.

## Key files

teleclaude/core/identity.py, teleclaude/core/command_handlers/\_session.py, teleclaude/types/commands.py, teleclaude/api/sessions_actions_routes.py, teleclaude/api/sessions_routes.py, teleclaude/core/command_mapper.py, teleclaude/core/models/\_adapter.py, teleclaude/core/models/\_session.py, teleclaude/core/agent_coordinator/\_fanout.py, teleclaude/transport/redis_transport/\_messaging.py, teleclaude/daemon_hook_outbox.py, teleclaude/core/db/\_sessions.py
