---
id: 'project/spec/feature/identity/human-identity-resolution'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Resolve a configured person from any inbound human signal — email, Telegram user id, Discord user id, WhatsApp phone number — into a canonical IdentityContext for downstream identity and routing.'
---

# Human Identity Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The single lookup service that maps any inbound human signal onto the operator's configured people. Every channel that surfaces a human — a terminal email login, a Next.js web session, a Telegram message, a Discord message, a WhatsApp message — funnels through `IdentityResolver` to answer "who is this, and what role do they hold?" The resolver indexes `global_config.people` (the source-of-truth list in `global.yml`) plus per-person config files (`people/<name>/teleclaude.yml`) that bind platform credentials. It builds five lookup maps (email, username, Telegram user id, Discord user id, WhatsApp phone) plus two Discord display-name overrides, and refreshes them automatically when the underlying config files change on disk. The resolver returns an `IdentityContext` carrying the canonical `person_name`, `person_email`, `person_role`, and a platform-specific `display_name_override`. For platforms that route unknown users into the system (Discord, WhatsApp), the resolver returns a partial `IdentityContext` with `person_role` set to `customer` so the platform identity is preserved for downstream notification routing even though no configured person matched. The terminal and web paths return an empty `IdentityContext` on miss — callers without a configured person are not auto-customer-promoted on those channels.

## Canonical fields

### Use cases

```
Given global.yml lists a person with email maurice@instrukt.ai, role admin, name "Maurice Faber"
When IdentityResolver.resolve_by_email("MAURICE@instrukt.ai") is called
Then it returns IdentityContext(person_name="Maurice Faber", person_email="maurice@instrukt.ai", person_role="admin")
And lookup is case-insensitive on email
```

```
Given a person whose role in global.yml is "operator" (not a known HUMAN_ROLES value)
When IdentityResolver.resolve_by_email(person.email) is called
Then the returned IdentityContext.person_role is "customer"
Because _normalize_role defaults unknown roles to HUMAN_ROLE_CUSTOMER
```

```
Given no person in global.yml has email unknown@example.com
When IdentityResolver.resolve_by_email("unknown@example.com") is called
Then it returns an empty IdentityContext (all fields None)
```

```
Given people/maurice/teleclaude.yml binds Telegram credentials user_id=123456789 to the maurice person
When IdentityResolver.resolve("telegram", {"user_id": "123456789", "telegram_user_id": "123456789"}) is called
Then it returns IdentityContext with person_email="maurice@instrukt.ai", person_role="admin", platform="telegram", platform_user_id="123456789"
```

```
Given people/maurice/teleclaude.yml binds Discord credentials user_id="555000111222333444" and nick="MoSr"
When IdentityResolver.resolve("discord", {"user_id": "555000111222333444"}) is called
Then it returns IdentityContext with display_name_override="MoSr", platform="discord", platform_user_id="555000111222333444"
And the resolved display_name property returns "MoSr" (override wins over person_name)
```

```
Given no configured person binds Discord user_id "999000111222333444"
When IdentityResolver.resolve("discord", {"user_id": "999000111222333444"}) is called
Then it returns IdentityContext(person_role="customer", platform="discord", platform_user_id="999000111222333444")
And person_name / person_email remain None
And the platform identity is preserved so downstream notification routing can still reach the Discord user
```

```
Given people/maurice/teleclaude.yml binds WhatsApp phone_number "+31 6 1234 5678"
When IdentityResolver.resolve("whatsapp", {"phone_number": "+31-6-1234-5678"}) is called
Then _normalize_phone_number strips non-digits to "31612345678"
And the lookup matches because both stored and queried numbers normalize to the same digits
And it returns IdentityContext with person_email="maurice@instrukt.ai", platform="whatsapp", platform_user_id="31612345678"
```

```
Given no configured person binds WhatsApp phone "31600000000"
When IdentityResolver.resolve("whatsapp", {"phone_number": "+31 6 0000 0000"}) is called
Then it returns IdentityContext(person_role="customer", platform="whatsapp", platform_user_id="31600000000")
And the WhatsApp identity is preserved for downstream routing
```

```
Given a session's persisted origin_metadata is {"discord": {"user_id": "555000111222333444"}, "telegram": {"user_id": "123456789"}}
When derive_identity_key(origin_metadata) is called
Then it returns "discord:555000111222333444"
Because Discord is preferred over Telegram in the precedence order (discord, telegram, whatsapp)
```

```
Given origin_metadata is {} (no platform signals)
When derive_identity_key(origin_metadata) is called
Then it returns None
```

```
Given global.yml has been edited on disk after the resolver was constructed
When any resolve_by_email / resolve / registered_people_count call runs
Then _reload_if_stale detects the mtime change on GLOBAL_CONFIG_PATH or PEOPLE_DIR
And reloads all lookup maps before answering
```

```
Given an IdentityContext with display_name_override="MoSr", person_name=None, person_email=None, platform_user_id=None
When IdentityContext.display_name is read
Then it returns "MoSr"
```

```
Given an IdentityContext with all naming fields empty (None or whitespace)
When IdentityContext.display_name is read
Then ValueError is raised
Because the context is in an invalid state with no resolvable display name
```

### Implementation pointers (v1)

- Class: `teleclaude/core/identity.py:51-315` (`IdentityResolver`)
- Singleton accessor: `teleclaude/core/identity.py:307-315` (`get_identity_resolver`)
- Dataclass: `teleclaude/core/identity.py:22-44` (`IdentityContext`)
- Email lookup: `teleclaude/core/identity.py:168-179` (`resolve_by_email`)
- Per-origin dispatch: `teleclaude/core/identity.py:187-286` (`resolve`)
- Identity-key derivation: `teleclaude/core/identity.py:289-304` (`derive_identity_key`)
- Mtime-based auto-reload: `teleclaude/core/identity.py:95-110` (`_reload_if_stale`)
- Index builder: `teleclaude/core/identity.py:112-166` (`_load_config`)
- Phone normalization: `teleclaude/core/identity.py:79-82` (`_normalize_phone_number`)
- Role normalization: `teleclaude/core/identity.py:72-77` (`_normalize_role`)
- Multi-user-mode gate: `IdentityResolver.registered_people_count` (`teleclaude/core/identity.py:181-185`), consumed by `_requires_terminal_login` / `_requires_tui_login`
- Config sources: `teleclaude/paths.py` exports `GLOBAL_CONFIG_PATH` and `PEOPLE_DIR`; loaders are `teleclaude/config/loader.py` (`load_global_config`, `load_person_config`)
- Role constants: `teleclaude/constants.py:51-56` (`HUMAN_ROLE_ADMIN`, `HUMAN_ROLE_MEMBER`, `HUMAN_ROLE_CONTRIBUTOR`, `HUMAN_ROLE_NEWCOMER`, `HUMAN_ROLE_CUSTOMER`, `HUMAN_ROLES`)
- Live callers:
  - Terminal/web verify-caller path: `teleclaude/api/auth.py:198-222,259-291` (`_build_terminal_identity`, `_resolve_terminal_role`)
  - CLI `whoami` role lookup: `teleclaude/cli/config_cli.py:60-66` (`_check_customer_guard`)
  - CLI `telec docs` role lookup: `teleclaude/cli/telec/handlers/docs.py:19-23` (`_current_terminal_role`)
  - Discord adapter (gateway): `teleclaude/adapters/discord/gateway_handlers.py:285`
  - Discord adapter (input): `teleclaude/adapters/discord/input_handlers.py:196,352`
  - Telegram adapter (private): `teleclaude/adapters/telegram/private_handlers.py:193-196`
  - Origin-based command resolution: `teleclaude/core/command_handlers/_session.py:113` (used during session creation to stamp `human_email` / `human_role`)
  - Adapter output display names: `teleclaude/core/adapter_client/_output.py:287`

### Cross-context references

- Reads from `config`: `load_global_config()` for the `people` list, `load_person_config()` for per-person credentials. The `people` list in `global.yml` and the per-person `teleclaude.yml` files together form the operator's source of truth for who exists in the system.
- Consumed by `agent_runtime`'s session-creation pipeline to stamp `sessions.human_email` and `sessions.human_role` at creation time (`core/command_handlers/_session.py`). Those stamped columns then feed `feature/identity/session-access-visibility` and `feature/identity/principal-resolution`.
- Consumed by `feature/identity/caller-verification` via the terminal-identity path — `_resolve_terminal_role` calls `resolve_by_email` to map the `x-telec-email` / `x-web-user-email` header onto a human role.
- The `customer`-role fallback for unknown Discord / WhatsApp users is the mechanism that lets the help-desk forum and customer-routing flows (`adapters/discord/input_handlers.py:193`) accept inbound messages from people who are not yet on the operator's `people` list. Without it those messages would be silently dropped.
- v2 replaces this resolver with a `Principal` aggregate materialized from the same config sources but with explicit `identity.principal.created` events on first observation; the v2 domain spec captures the upgrade.

## Known caveats

- The resolver is process-singleton and module-global (`_resolver_instance` in `teleclaude/core/identity.py:307`). Test isolation that needs to reset the singleton must manipulate the module attribute directly.
- The mtime-based reload checks `GLOBAL_CONFIG_PATH.st_mtime_ns` and `PEOPLE_DIR.st_mtime_ns` — the directory mtime only changes when entries are added or removed, not when an existing `people/<name>/teleclaude.yml` is edited in place. An edit to an existing per-person file does NOT trigger a reload until the global file or the directory itself changes. This is a known v1 limitation.
- The customer-role fallback for unknown platform identities is asymmetric: Discord and WhatsApp produce it; Telegram and web/terminal do not. The asymmetry reflects which platforms expect inbound customer contact (Discord help desk, WhatsApp business inbox) versus which require pre-registration (Telegram private, web NextAuth).
- `resolve_by_email` is case-insensitive on input but the returned `person_email` is the EXACT cased value from `global.yml`. Downstream code that compares emails should normalize on both sides.
- The Discord display-name override is stored twice — once by email and once by user_id — because the lookup site differs (web shows override-by-email; Discord shows override-by-user-id). Both must be updated coherently; the v1 builder writes both from the same source field.
- The resolver does not produce events. v2 promotes person registration to a first-class `identity.principal.created` event so downstream contexts (memory, session_mirrors, integration) can subscribe instead of polling config.
- `IdentityContext.display_name` raises `ValueError` on an all-empty context — this is a contract violation, not a runtime error to handle. Callers should not invoke `display_name` on an empty context returned from a miss; the empty context is meant to be inspected via `person_name is None` before any display.
