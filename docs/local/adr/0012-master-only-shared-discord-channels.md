---
date: '2026-05-28'
description: 'Shared (generic) Discord channels — Operations, Help Desk (Customer Sessions, Escalations), and Team — are provisioned by the master computer only. Non-master computers resolve them by name but never create, so a shared Discord app cannot accrue duplicate channels.'
number: '12'
visibility: 'public'
---

# ADR-0012: Shared Discord Channels Are Provisioned by the Master Computer Only — ADR

## Context

Discord is the single admin adapter, and all computers in a multi-computer deployment interface with the same Discord app and guild. Every computer's Discord adapter runs `_ensure_discord_infrastructure` on `on_ready`, which provisions categories and channels.

The channel structure splits into two kinds:

- **Per-computer**: the `Projects - {computer}` category and its forums. The category name embeds the computer name, so each machine owns a uniquely-named category and they never collide.
- **Shared/generic**: `Operations` (#announcements, #general), `Help Desk` (Customer Sessions forum, Escalations forum, #operator-chat), and `Team` (per-person channels). These names are identical across the guild regardless of which computer provisions them.

Each computer keeps its own `config.yml` with its own cached channel IDs. A non-master computer has no cached ID for a shared channel, so it entered the find-or-create path. The existing name-search dedup in the create helpers usually finds an already-created channel, but it is a boot race: when computers come up together (the multi-computer revival scenario), a second computer's guild cache has not yet observed the master's freshly-created forum, so both create one. This produced duplicate `Customer Sessions` / `Escalations` forums. The per-computer `Projects - {computer}` category was immune because its name is unique per machine — which is why that side already merged correctly.

The decision needed: make duplicate shared channels structurally impossible, not merely less likely.

## Decision

Shared Discord channels are provisioned by the master computer (`computer.is_master`) only. Non-master computers resolve shared channels by name (so routing to Help Desk and Escalations still works once the master provisions them) but never create them.

The mechanism is a keyword-only `create: bool = True` flag threaded through the provisioning primitives — `_ensure_category`, `_find_or_create_forum`, `_find_or_create_text_channel`, and the team-channel path. When `create=False`, each primitive resolves an existing channel by name and otherwise returns `None` instead of creating. `_ensure_discord_infrastructure` reads `is_master` once and passes `create=is_master` to every shared-category, shared-forum, shared-text-channel, and team-channel call. The per-computer `Projects - {computer}` category, its `Unknown` catch-all forum, and the per-project forums are unchanged — every computer always provisions its own.

The master is the sole advertiser of shared channels, with no fallback: a non-master never creates a shared channel even when the master is offline or has not yet provisioned.

## Consequences

**Positive:**

- Duplicate shared channels are structurally impossible across a shared Discord app, independent of boot timing or guild-cache staleness — the boot race that caused the duplicates can no longer create anything on a non-master.
- The fix is backward compatible: `create` is keyword-only, so no positional call site shifts, and master behavior is byte-for-byte unchanged (`create=True` everywhere).
- The system self-heals after cleanup: once duplicate forums are deleted in Discord, any non-master config still caching a now-deleted duplicate ID fails `_validate_channel_id` on next restart and re-resolves to the master's channel by name.

**Negative:**

- A non-master computer cannot route to a shared channel until the master has provisioned it. If the master is offline at a non-master's first boot, the non-master's shared-channel IDs stay `None` and shared routing (e.g., Help Desk threads originating on that computer) is unavailable until the master comes up. This is the intended ordering: shared infrastructure depends on the master.
- This change only stops new duplicates. Pre-existing duplicate forums created before the fix must be deleted manually in Discord.
- Correct behavior now depends on exactly one computer carrying `is_master: true`. Two masters reintroduce the race; zero masters means shared channels are never created.

## Alternatives Considered

- **Stronger dedup / distributed locking instead of an ownership rule.** Force a guild fetch before every create, or take a cross-computer lock around shared-channel creation. Rejected: it fights the symptom (the race) rather than the cause (every computer believing it must provision shared infra), adds latency and a coordination dependency, and is still best-effort against Discord's eventually-consistent caches. The ownership rule removes the race entirely.
- **Per-computer shared channels (namespace Help Desk like Projects).** Rejected: the whole point of Help Desk / Escalations / Operations is that they are guild-wide and shared; per-computer copies would fragment customer sessions and escalations across machines.
- **Dynamic leader election instead of a static `is_master` flag.** Rejected as over-engineered for the current deployment. `is_master` already exists in config and is used by the Telegram adapter; reusing it keeps one consistent notion of "the primary computer." Election can supersede this ADR if the deployment topology ever demands it.
