---
description: 'Resolve a configured person from any inbound human signal — email, Telegram user id, Discord user id, WhatsApp phone number — into a canonical IdentityContext for downstream identity and routing.'
visibility: 'public'
---

# Human Identity Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The single lookup capability that maps any inbound human signal onto the operator's configured people. Every channel that surfaces a human — a terminal email login, a web session, a Telegram message, a Discord message, a WhatsApp message — funnels through human-identity resolution to answer "who is this, and what role do they hold?" The resolver indexes the configured `people` list (the source-of-truth list in global config) plus per-person config bindings for platform credentials. It builds lookup maps over email, username, Telegram user id, Discord user id, and WhatsApp phone, plus Discord display-name overrides, and refreshes them automatically when the underlying config changes on disk. The resolver returns an `IdentityContext` carrying the canonical `person_name`, `person_email`, `person_role`, and a platform-specific `display_name_override`. For platforms that route unknown users into the system (Discord, WhatsApp), the resolver returns a partial `IdentityContext` with `person_role` set to `customer` so the platform identity is preserved for downstream notification routing even though no configured person matched. The terminal and web paths return an empty `IdentityContext` on miss — callers without a configured person are not auto-customer-promoted on those channels.

## Canonical fields

### Use cases

```
Given the global config lists a person with email maurice@instrukt.ai, role admin, name "Maurice Faber"
When the resolver is queried by email "MAURICE@instrukt.ai"
Then it returns IdentityContext(person_name="Maurice Faber", person_email="maurice@instrukt.ai", person_role="admin")
And lookup is case-insensitive on email
```

```
Given a person whose role in global config is "operator" (not a known HUMAN_ROLES value)
When the resolver is queried by that person's email
Then the returned IdentityContext.person_role is "customer"
Because role normalization defaults unknown roles to HUMAN_ROLE_CUSTOMER
```

```
Given no person in global config has email unknown@example.com
When the resolver is queried by that email
Then it returns an empty IdentityContext (all fields None)
```

```
Given the per-person config for Maurice binds Telegram credentials user_id=123456789
When the resolver is queried for origin "telegram" with payload {"user_id": "123456789", "telegram_user_id": "123456789"}
Then it returns IdentityContext with person_email="maurice@instrukt.ai", person_role="admin", platform="telegram", platform_user_id="123456789"
```

```
Given the per-person config for Maurice binds Discord credentials user_id="555000111222333444" and nick="MoSr"
When the resolver is queried for origin "discord" with payload {"user_id": "555000111222333444"}
Then it returns IdentityContext with display_name_override="MoSr", platform="discord", platform_user_id="555000111222333444"
And the resolved display_name property returns "MoSr" (override wins over person_name)
```

```
Given no configured person binds Discord user_id "999000111222333444"
When the resolver is queried for origin "discord" with payload {"user_id": "999000111222333444"}
Then it returns IdentityContext(person_role="customer", platform="discord", platform_user_id="999000111222333444")
And person_name / person_email remain None
And the platform identity is preserved so downstream notification routing can still reach the Discord user
```

```
Given the per-person config for Maurice binds WhatsApp phone_number "+31 6 1234 5678"
When the resolver is queried for origin "whatsapp" with payload {"phone_number": "+31-6-1234-5678"}
Then phone normalization strips non-digits to "31612345678"
And the lookup matches because both stored and queried numbers normalize to the same digits
And it returns IdentityContext with person_email="maurice@instrukt.ai", platform="whatsapp", platform_user_id="31612345678"
```

```
Given no configured person binds WhatsApp phone "31600000000"
When the resolver is queried for origin "whatsapp" with payload {"phone_number": "+31 6 0000 0000"}
Then it returns IdentityContext(person_role="customer", platform="whatsapp", platform_user_id="31600000000")
And the WhatsApp identity is preserved for downstream routing
```

```
Given a session's persisted origin_metadata is {"discord": {"user_id": "555000111222333444"}, "telegram": {"user_id": "123456789"}}
When identity-key derivation runs over the origin metadata
Then it returns "discord:555000111222333444"
Because Discord is preferred over Telegram in the precedence order (discord, telegram, whatsapp)
```

```
Given origin_metadata is {} (no platform signals)
When identity-key derivation runs
Then it returns None
```

```
Given the global config has been edited on disk after the resolver was constructed
When any resolver query runs
Then the staleness check detects the mtime change on the global config or people directory
And reloads all lookup maps before answering
```

```
Given an IdentityContext with display_name_override="MoSr", person_name=None, person_email=None, platform_user_id=None
When IdentityContext.display_name is read
Then it returns "MoSr"
```

```
Given an IdentityContext with all naming fields empty (None or whitespace)
When the identity context's display name is read
Then an identity error is raised
Because the context is in an invalid state with no resolvable display name
```

### Cross-context references

- Reads from the `config` bounded context: the `people` list in global config and per-person config files together form the operator's source of truth for who exists in the system.
- Consumed by `agent_runtime`'s session-creation pipeline to stamp `sessions.human_email` and `sessions.human_role` at creation time. Those stamped columns then feed `feature/identity/session-access-visibility` and `feature/identity/principal-resolution`.
- Consumed by `feature/identity/caller-verification` via the terminal-identity path — the verifier calls the resolver to map the inbound terminal-email signal onto a human role.
- The `customer`-role fallback for unknown Discord / WhatsApp users is the mechanism that lets the help-desk forum and customer-routing flows in the Discord adapter accept inbound messages from people who are not yet on the operator's `people` list. Without it those messages would be silently dropped.
- v2 replaces this resolver with a `Principal` aggregate materialized from the same config sources but with explicit `identity.principal.created` events on first observation; the v2 domain spec captures the upgrade.

## Known caveats

- The resolver is process-singleton and module-global within the identity context. Test isolation that needs to reset the singleton must manipulate the module attribute directly.
- The mtime-based reload checks the global config file and the people directory — the directory mtime only changes when entries are added or removed, not when an existing per-person file is edited in place. An edit to an existing per-person file does NOT trigger a reload until the global file or the directory itself changes. This is a known v1 limitation.
- The customer-role fallback for unknown platform identities is asymmetric: Discord and WhatsApp produce it; Telegram and web/terminal do not. The asymmetry reflects which platforms expect inbound customer contact (Discord help desk, WhatsApp business inbox) versus which require pre-registration (Telegram private, web auth).
- Email lookup is case-insensitive on input but the returned `person_email` is the EXACT cased value from the configured `people` list. Downstream code that compares emails should normalize on both sides.
- The Discord display-name override is stored twice — once by email and once by user_id — because the lookup site differs (web shows override-by-email; Discord shows override-by-user-id). Both must be updated coherently; the index builder writes both from the same source field.
- The resolver does not produce events. v2 promotes person registration to a first-class `identity.principal.created` event so downstream contexts (memory, session_mirrors, integration) can subscribe instead of polling config.
- The identity context's display-name capability raises an identity error on an all-empty context — this is a contract violation, not a runtime error to handle. Callers should not read the display name on an empty context returned from a miss; the empty context is meant to be inspected via `person_name is None` before any display.
