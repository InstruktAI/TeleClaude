"""Field-level merge of a writer's change onto the row it commits against.

A previous-machine writer reads the state, edits the typed model and commits. Writing the whole of it back overwrites
whatever another writer committed between the read and the write. The merge writes only what the writer changed:
the leaf fields that differ between the state it read and the state it ends with, applied to the state the commit
transaction reads. A field the writer did not touch keeps the value another writer committed, and a field both wrote
is the later committer's.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from teleclaude.types.state_value import StateValue

type StatePath = tuple[str, ...]


@dataclass(frozen=True)
class FieldChange:
    """One leaf field a writer changed: where it is, and what it now holds (``removed`` when it deleted the field)."""

    path: StatePath
    value: StateValue
    removed: bool = False


def changed_fields(
    baseline: dict[str, StateValue], final: dict[str, StateValue], prefix: StatePath = ()
) -> list[FieldChange]:
    """The leaf fields that differ between the state a writer read and the state it ended with.

    Nested objects are compared field by field; lists and scalars are compared whole, so a changed list is one change.
    """
    changes: list[FieldChange] = []
    for key in baseline.keys() | final.keys():
        path = (*prefix, key)
        before = baseline.get(key)
        after = final.get(key)
        if key not in final:
            changes.append(FieldChange(path, None, removed=True))
        elif key not in baseline:
            changes.append(FieldChange(path, after))
        elif isinstance(before, dict) and isinstance(after, dict):
            changes.extend(changed_fields(before, after, path))
        elif before != after:
            changes.append(FieldChange(path, after))
    return changes


def apply_changes(current: dict[str, StateValue], changes: list[FieldChange]) -> dict[str, StateValue]:
    """The current stored state with the writer's changed fields applied; nothing else is touched."""
    merged = copy.deepcopy(current)
    for change in changes:
        node = merged
        for key in change.path[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        leaf = change.path[-1]
        if change.removed:
            node.pop(leaf, None)
        else:
            node[leaf] = copy.deepcopy(change.value)
    return merged
