# telec todo dump — Input

## Context

Today `telec todo create` scaffolds a todo folder for manual iteration. The human
creates, then drives the lifecycle — running prepare, dispatching builds, etc. This is
fine for deliberate work, but it creates friction for the five-minute brain dump: you
have an idea, you dump it, you want the system to take over.

`telec bugs report` solved this for bugs — scaffold + dispatch + fix in one coupled
chain. But it's tightly coupled: the report command runs the entire lifecycle inline.
That's the pattern we're moving away from.

## What we want

`telec todo dump` — a fire-and-forget brain dump that:

1. Scaffolds the todo folder (like `create`)
2. Writes the brain dump into `input.md`
3. Fires a notification event: `todo.dumped` (or `todo.needs_processing`)
4. Returns immediately

The notification service routes the event to subscribed agents (prepare-quality-runner
or whatever handler is registered for that event type). The agent picks it up, fleshes
out requirements, writes an implementation plan, runs DOR assessment. The human's
five-minute dump becomes a fully processed todo — or a todo flagged with specific
blockers needing human decision.

## The key distinction

| Command             | Signal                              | Processing                                 |
| ------------------- | ----------------------------------- | ------------------------------------------ |
| `telec todo create` | No signal. Workspace for iteration. | Human-driven.                              |
| `telec todo dump`   | Fires notification immediately.     | Agent-driven via notification service.     |
| `telec bugs report` | Inline dispatch (coupled).          | Tightly coupled lifecycle. To be migrated. |

## Dependency

Depends on notification-service — the notification IS the decoupling mechanism.
Without it, dump would have to fall back to inline dispatch (defeating the purpose).

## CLI shape (preliminary)

```
telec todo dump <description> [--slug <slug>] [--tags <tags>]
```

Accepts freeform text as the brain dump. Optionally auto-generates a slug from the
description. Writes `input.md` with the dump content. Fires the notification. Done.
