---
description: TypeScript snapshot assertion and migration mechanics using the repository-declared Vitest runner.
---

# TypeScript Snapshot Testing — Procedure

## Required reads

@~/.teleclaude/docs/software-development/procedure/snapshot-testing.md
@~/.teleclaude/docs/software-development/policy/typescript/testing.md
@~/.teleclaude/docs/software-development/policy/typescript/core.md

## Goal

Implement the generic snapshot-testing contract in TypeScript with Vitest snapshots, asymmetric property matchers, and production-owned constant identity.

## Preconditions

- The project has opted into TypeScript test authorship.
- Vitest is exposed through the repository's declared package script.

## Steps

1. Snapshot complete emitted values with `toMatchInlineSnapshot()` by default. Use a file snapshot when inline output would make the test difficult to scan.
2. Normalize unstable object properties through Vitest asymmetric matchers such as `expect.any(...)` or `expect.stringMatching(...)`, scoped only to the unstable fields.
3. For a non-empty boundary guard, use a typed helper that checks presence without grading wording.
4. Represent protocol identifiers and closed vocabularies with a production-owned `as const` object or literal-union owner. Import the member for identity comparison and snapshot the owner separately when its serialized values are contractual.
5. Replace equality, containment, prefix, suffix, and regular-expression assertions over emitted text with a snapshot. Assert thrown failures by error type rather than message text.
6. Run the declared package test script through `telec code test`, read every snapshot diff, and only then run `telec code test --update-snapshots` when the delta matches intent.

## Outputs

- TypeScript string contracts are covered through Vitest at their public boundary.
- Nondeterministic fields are normalized explicitly and narrowly.
- Accepted snapshot files are committed with the behavior that changed them.

## Recovery

- If Vitest reports an unexpected snapshot delta, fix the producer and rerun without snapshot update.
- If matchers would hide meaningful behavior, make the public output deterministic before snapshotting it.
