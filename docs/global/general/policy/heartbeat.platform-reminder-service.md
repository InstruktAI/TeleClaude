---
description: Compatibility entrypoint preserving legacy Heartbeat policy references while the agent-intent mechanism is named Reminder.
---

# Heartbeat Compatibility — Policy

## Required reads

- @~/.teleclaude/docs/general/policy/reminder.md

## Rules

- In agent instructions, a future-self intent timer is a reminder and follows
  the Agent Reminder policy loaded above.
- The term heartbeat remains correct only for infrastructure liveness, lease,
  peer-refresh, cache-health, and operation-health mechanisms.
- A legacy reference to this snippet resolves to the Agent Reminder policy; it
  does not preserve runtime-local timer instructions or the old heartbeat
  vocabulary for agent intent.

## Rationale

The compatibility entrypoint keeps older required-read paths valid while the
ubiquitous language separates future-self intent from infrastructure liveness.

## Scope

- Legacy references to `general/policy/heartbeat`.

## Enforcement

- New agent-intent documentation references `general/policy/reminder`.
- Genuine infrastructure heartbeat names are not migrated through this alias.

## Exceptions

- None.
