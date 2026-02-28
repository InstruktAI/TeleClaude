# telec content dump — Input

## Context

The publications pipeline (`publications/inbox/`) models content production as a
professional agency. Agents and humans dump raw narratives. Writers refine. Publishers
distribute. Currently, dumping requires manually creating the folder, writing
`content.md`, optionally adding `meta.yaml`. That friction discourages the five-minute
brain dump that produces the best raw material.

## What we want

`telec content dump` — a fire-and-forget content dump that:

1. Creates a dated inbox folder (`publications/inbox/YYYYMMDD-<slug>/`)
2. Writes the brain dump into `content.md`
3. Writes `meta.yaml` with author and optional tags
4. Fires a notification event: `content.dumped` (or `content.needs_processing`)
5. Returns immediately

The notification service routes the event to the writer agent (or content processing
pipeline). The writer checks it against reality, refines it, and passes it to the
publisher. The human's dump becomes a polished piece without touching it again.

## The key distinction

| Command                         | Signal                                    | Processing                             |
| ------------------------------- | ----------------------------------------- | -------------------------------------- |
| `telec content create` (future) | No signal. Iterate with writers manually. | Human-driven collaboration.            |
| `telec content dump`            | Fires notification immediately.           | Agent-driven via notification service. |

## Dependency

Depends on event-platform — same pattern as `telec todo dump`. The notification
triggers downstream processing.

## CLI shape (preliminary)

```
telec content dump <description-or-text> [--slug <slug>] [--tags <tags>] [--author <agent>]
```

Accepts freeform text as the content dump. Auto-generates a dated slug. Writes the
inbox entry. Fires the notification. Done.

## Relationship to marketing service

This is the first primitive of the marketing service package. The content dump is the
ingestion point. Writers and publishers are agents that consume notifications and
produce polished, distributed content. The full agency model (writer, publisher,
channel selection, cadence) builds on top of this dump primitive.
