---
description: 'TypeScript-specific testing idioms layered over the generic testing policy: vitest runner via package.json, file/binding conventions, snapshots, and the no-unit-test stance.'
visibility: 'public'
---

# TypeScript Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md

## Rules

1. **No agent-authored unit tests.** TypeScript's types are erased at runtime and do not enforce
   behavioral correctness — under the generic rule it is a compiler-less language for testing
   purposes. Behavior is verified by functional and smoke tests.
2. **Test files mirror the feature spec.** A spec at `docs/project/spec/feature/<domain>/<slug>.md`
   is covered by `<frontend_root>/tests/<domain>/<slug>.test.ts`. Contract-defining tooling is not
   tested — see the generic policy.
3. **Bind scenarios** with the project's `spec("<spec_id>", "<UC-id>")` tag at the top of each test;
   the functional/integration tier is a per-test tag, never a directory.
4. **Run through the declared `package.json` test script**, so the runner and its config have a
   single source of truth. Snapshots use vitest's built-in `toMatchSnapshot` /
   `toMatchInlineSnapshot`; CI never updates.
5. **Coverage** is measured against the scenario inventory; TypeScript binding completeness and
   drift are checked at review.

## Rationale

- TypeScript's structural typing catches shape errors but does not guarantee runtime behavior, and
  agents produce the same green-theater unit tests here as in any dynamic language. The generic
  behavioral model applies in full; this snippet fixes the TypeScript idioms that realize it.

## Scope

- All TypeScript code in this repository and in projects managed by this platform.

## Enforcement

- TypeScript spec bindings are checked at review.
- The reviewer rejects agent-authored unit tests.
- Agent-authored TypeScript unit tests, and test files outside the doctrine path
  `<frontend_root>/tests/<domain>/<slug>.test.ts(x)`, are structurally blocked; the mechanism is
  owned by the harness and tooling. Playwright e2e specs (`*.spec.ts`) are functional.

## Exceptions

- None.
