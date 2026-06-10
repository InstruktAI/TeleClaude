---
description: 'Delete a memory observation by id, with a not-found signal when nothing matched.'
visibility: 'public'
---

# Observation Delete — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

A memory observation can be removed by id. The memory service deletes the observation and ensures the search index is kept in sync. Removal of a non-existent observation is signalled as a not-found error. No authorization is enforced; any caller able to reach the memory surface can delete any observation.

## Canonical fields

### Use cases

#### Delete via CLI

```
Given a human or agent runs `telec memories delete <id>`
When the CLI parses arguments
Then <id> must be parseable as an integer (otherwise the CLI prints "Invalid ID '<id>': must be a number." and exits 1)
And the CLI asks the memory service to delete the observation
And on success prints `Deleted observation #<id>`
And on any error prints `Error: <detail>` and exits 1
```

#### Delete

```
Given a caller asks the memory service to delete an observation by id
When the request is processed
Then on a match the observation is removed and the deletion is acknowledged
And on no match a not-found signal is returned
And the search index is kept in sync with the removal
```

### Cross-context references

- None. Delete is contained within the `memory` context.

## Known caveats

- **No event emitted on delete.** Deletion produces no `memory.observation.deleted` event. Subscribers that want to react to deletions must poll.
- **No authorization check.** No author-or-admin authorization is enforced on delete (the memory domain spec calls for "author or authorized operator"). Any caller can delete any observation by id.
- **No bulk delete surface.** Deletion is one-at-a-time. There is no batch delete analogous to bulk-fetch.
- **Hard delete only.** No soft-delete / tombstone behavior is provided. The observation is removed; the search-index entry is removed; no audit record survives.
- **Idempotency surfaces as not-found.** A second deletion of the same id returns not-found. Callers needing idempotent semantics should treat not-found as success on retry.
