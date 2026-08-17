---
description: Verified Textual Worker API semantics for @work groups, exclusivity, cancellation, and result ordering.
---

# Textual Worker Concurrency

## Verified behavior

- The `@work` decorator accepts a `group` parameter — "A short string to
  identify a group of workers" — defaulting to `'default'`, and an `exclusive`
  parameter defaulting to `False`.
- `exclusive=True` is documented as "Cancel all workers in the same group":
  starting an exclusive worker cancels every existing worker sharing that
  group identifier before the new one runs.
- Cancellation scope is the group. Workers in different groups neither cancel
  nor are cancelled by each other, whatever their `exclusive` setting.
- The workers guide motivates `exclusive` with response ordering: "when
  pulling data from the network, there is no guarantee that you will receive
  the responses in the same order as the requests." Exclusivity resolves this
  only inside one group, by cancelling the older request outright.
- Textual provides no ordering or freshness guarantee across groups: two
  workers in different groups may complete in any order, and the framework
  does not arbitrate which result an application applies.
- A worker can be cancelled explicitly at any time via `Worker.cancel()`,
  which raises `CancelledError` inside the coroutine.
- Workers are tied to the DOM node (widget, screen, or app) where they are
  created and are cleaned up automatically when that node is removed.

## Gaps

- The prose workers guide documents `exclusive`, `thread`, and
  `exit_on_error` but not `group`; the `group` semantics above come from the
  API reference for the `@work` decorator.

## Sources

- https://textual.textualize.io/guide/workers/
- https://textual.textualize.io/api/work/
