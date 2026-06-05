---
id: 'software-development/policy/typescript/testing'
type: 'policy'
scope: 'domain'
visibility: 'public'
description: 'TypeScript-specific testing idioms layered over the generic testing policy: vitest runner via package.json, file/binding conventions, snapshots, and the no-unit-test stance.'
---

# TypeScript Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md

## Rules

1. **No agent-authored unit tests.** TypeScript's types are erased at runtime and do not enforce
   behavioral correctness — under the generic rule it is a compiler-less language for testing
   purposes. Behavior is verified by functional and smoke tests.
2. **Test files mirror the feature spec.** A spec at `docs/project/spec/feature/<domain>/<slug>.md`
   is covered by `<frontend_root>/tests/feature/<domain>/<slug>.test.ts`. Tests for tooling live
   outside the feature mirror and are exempt.
3. **Bind scenarios** with the project's `spec("<spec_id>", "<UC-id>")` tag at the top of each test;
   the functional/integration tier is a per-test tag, never a directory.
4. **Run through `package.json`** — invoke the declared `test` script (`npm test`), never `npx`
   directly, so the runner and its config have a single source of truth. Snapshots use vitest's
   built-in `toMatchSnapshot` / `toMatchInlineSnapshot` (`vitest -u` to update; CI never updates).
5. **Coverage and drift** are reported by the spec-coverage tool against the scenario inventory.

## Rationale

- TypeScript's structural typing catches shape errors but does not guarantee runtime behavior, and
  agents produce the same green-theater unit tests here as in any dynamic language. The generic
  behavioral model applies in full; this snippet fixes the TypeScript idioms that realize it.

## Scope

- All TypeScript code in this repository and in projects managed by this platform.

## Enforcement

- The spec-coverage tool reports bound / unbound / duplicate / orphan / stale.
- The reviewer rejects agent-authored unit tests.

## Exceptions

- None.
