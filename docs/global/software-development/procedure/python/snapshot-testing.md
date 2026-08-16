---
description: Python snapshot assertion and migration mechanics using syrupy and pytest.
---

# Python Snapshot Testing — Procedure

## Required reads

@~/.teleclaude/docs/software-development/procedure/snapshot-testing.md
@~/.teleclaude/docs/software-development/policy/python/testing.md
@~/.teleclaude/docs/software-development/policy/python/core.md

## Goal

Implement the generic snapshot-testing contract in Python with syrupy, pytest exception assertions, and production-owned enum identity.

## Preconditions

- The project has opted into Python test authorship.
- `syrupy` is configured through the repository's declared Python test tooling.

## Steps

1. Receive `snapshot: SnapshotAssertion` and compare the complete emitted value with `assert rendered == snapshot`.
2. Keep snapshots inline by default. Use a file snapshot when the captured output is large enough that the test becomes difficult to scan.
3. Normalize unstable properties with syrupy's `path_type` or `path_value` matchers before comparison. Keep the normalization narrowly scoped to the unstable field.
4. For a non-empty boundary guard, assert the value's truthiness through a typed helper; do not inspect its wording.
5. Represent protocol identifiers and closed vocabularies with the production-owned enum or nominal type. Import that member into the test for identity comparison, and snapshot its serialized schema value separately when that wire value is contractual.
6. Replace equality, membership, prefix, suffix, search, and regex assertions over emitted text with a syrupy snapshot. Assert raised failures with `pytest.raises(<ExceptionType>)`, not their message text.
7. Run `telec code test`, read every snapshot diff, and only then run `telec code test --update-snapshots` when the delta matches intent.

## Outputs

- Python string contracts are covered through syrupy at their public boundary.
- Nondeterministic fields are normalized explicitly and narrowly.
- Accepted snapshot files are committed with the behavior that changed them.

## Recovery

- If pytest reports an unexpected snapshot delta, fix the producer and rerun without snapshot update.
- If syrupy cannot normalize the value without hiding behavior, make the public output deterministic before snapshotting it.
