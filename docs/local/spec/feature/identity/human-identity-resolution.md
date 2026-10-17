---
description: 'Resolve a configured person from any inbound human signal — email, Telegram user id, Discord user id, WhatsApp phone number — into a canonical IdentityContext for downstream identity and routing.'
visibility: 'public'
---

# Human Identity Resolution — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The single lookup capability that maps any inbound human signal onto the operator's configured people. Every channel that surfaces a human — a terminal email login, a Telegram message, a Discord message, a WhatsApp message — funnels through human-identity resolution to answer "who is this, and what role do they hold?" The resolver indexes the configured `people` list (the source-of-truth list in global config) plus per-person config bindings for platform credentials. It builds lookup maps over email, username, Telegram user id, Discord user id, and WhatsApp phone, plus Discord display-name overrides, and refreshes them automatically when the underlying config changes on disk. The resolver returns an `IdentityContext` carrying the canonical `person_name`, `person_email`, `person_role`, and a platform-specific `display_name_override`. For the conversation platforms, which route unknown users into the system (Telegram, Discord, WhatsApp), the resolver returns a partial `IdentityContext` with `person_role` set to `customer` so the platform identity is preserved for downstream notification routing even though no configured person matched. The terminal path returns an empty `IdentityContext` on miss — callers without a configured person are not auto-customer-promoted on that channel.

When a Discord account is bound, its current avatar URL is stored with the person's
credential binding. For configured people whose Discord credential binding carries an
avatar URL, the resolved identity also carries that stored presentation so downstream
surfaces can present the human consistently without querying Discord during delivery.

The resolved `IdentityContext` also carries the person's canonical `slug` as
`person_slug`. The resolver discovers each person's per-person config binding by
their slug-named workspace folder (`~/.teleclaude/people/<slug>/`) rather than
by a name-derived key, and channels that scaffold or bind a workspace — Discord
and Telegram onboarding — thread `person_slug` through to those folder-keyed
operations.

WhatsApp phone matching removes non-digit characters from both the stored and
incoming numbers before lookup. A registered person with no platform role
resolves with `person_role` set to `customer`; company roles remain scoped to
their objects and are resolved separately (`local/projects/teleclaude/design/architecture/scoped-roles`).

## Canonical fields

### Use cases

#### UC-HIR-PERSON-SLUG: Resolved IdentityContext carries the canonical person_slug

#### UC-HIR-DISCORD-AVATAR-CAPTURE: Discord invitation binding captures the person's avatar

#### UC-HIR-DISCORD-AVATAR-RESOLUTION: Resolved identity exposes the stored Discord presentation

#### UC-HIR-NO-PLATFORM-ROLE: A registered person without a platform role resolves as customer at platform scope

#### UC-HIR-TELEGRAM-CUSTOMER: An unknown Telegram user resolves as customer

### Cross-context references

- Reads from the `config` bounded context: the `people` list in global config and per-person config files together form the operator's source of truth for who exists in the system.
- Consumed by `agent_runtime`'s session-creation pipeline to stamp `sessions.human_email` and `sessions.human_role` at creation time. Those stamped columns then feed `feature/identity/session-access-visibility` and `feature/identity/principal-resolution`.
- Consumed by the client-side caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6) — a caller at a terminal or in the TUI resolves to a person and role through the resolver.
- The `customer`-role fallback for unknown Telegram / Discord / WhatsApp users is the mechanism that lets conversation entry accept inbound messages from people who are not on the operator's `people` list (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`). Whether such a message opens a session is decided there, not by the resolver.
- v2 replaces this resolver with a `Principal` aggregate materialized from the same config sources but with explicit `identity.principal.created` events on first observation; the v2 domain spec captures the upgrade.

## Known caveats

- The resolver is process-singleton and module-global within the identity context. Test isolation that needs to reset the singleton must manipulate the module attribute directly.
- The mtime-based reload checks the global config file and the people directory — the directory mtime only changes when entries are added or removed, not when an existing per-person file is edited in place. An edit to an existing per-person file does NOT trigger a reload until the global file or the directory itself changes. This is a known v1 limitation.
- The customer-role fallback for unknown platform identities is asymmetric: the conversation platforms (Telegram, Discord, WhatsApp) produce it; the terminal does not. A conversation platform is where an outsider may reach a help desk, while a terminal login requires registration.
- Email lookup is case-insensitive on input but the returned `person_email` is the EXACT cased value from the configured `people` list. Downstream code that compares emails should normalize on both sides.
- The Discord display-name override is stored twice — once by email and once by user_id — because the lookup site differs (people-config surfaces show override-by-email; Discord shows override-by-user-id). Both must be updated coherently; the index builder writes both from the same source field.
- The resolver does not produce events. v2 promotes person registration to a first-class `identity.principal.created` event so downstream contexts (memory, session_mirrors, integration) can subscribe instead of polling config.
- The identity context's display-name capability raises an identity error on an all-empty context — this is a contract violation, not a runtime error to handle. Callers should not read the display name on an empty context returned from a miss; the empty context is meant to be inspected via `person_name is None` before any display.
