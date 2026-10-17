---
description: 'Delete a memory observation by id, with a not-found signal when nothing matched.'
visibility: 'public'
---

# Observation Delete — Spec

## What it is

A memory observation can be removed by id. The memory service deletes the observation and ensures the search index is kept in sync. Removal of a non-existent observation is signalled as a not-found error. No authorization is enforced; any caller able to reach the memory surface can delete any observation.
The CLI requires an integer id, rejects invalid input before deletion, confirms a successful removal, and reports a missing observation as not found.

## Canonical fields

### Use cases

#### Delete via CLI

```gherkin
Scenario: An operator removes an observation
  Given a human operator wants to remove a stored observation they can reach
  When they delete it by its integer id
  Then the observation is removed and the CLI confirms the deletion

Scenario: Invalid or missing IDs do not claim a deletion
  Given an operator enters an invalid ID or names no stored observation
  When they request deletion
  Then the CLI reports the input or not-found condition and returns failure
  And no other observation is removed
```

### Cross-context references

- None. Delete is contained within the `memory` context.

## Known caveats

- **No event emitted on delete.** Deletion produces no `memory.observation.deleted` event. Subscribers that want to react to deletions must poll.
- **No authorization check.** No author-or-admin authorization is enforced on delete (the memory domain spec calls for "author or authorized operator"). Any caller can delete any observation by id.
- **No bulk delete surface.** Deletion is one-at-a-time. There is no batch delete.
- **Hard delete only.** No soft-delete / tombstone behavior is provided. The observation is removed; the search-index entry is removed; no audit record survives.
- **Idempotency surfaces as not-found.** A second deletion of the same id returns not-found. Callers needing idempotent semantics should treat not-found as success on retry.
