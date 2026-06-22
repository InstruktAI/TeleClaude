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
4. **Run through `package.json`** — invoke the declared `test` script (`npm test`), never `npx`
   directly, so the runner and its config have a single source of truth. Snapshots use vitest's
   built-in `toMatchSnapshot` / `toMatchInlineSnapshot` (`vitest -u` to update; CI never updates).
5. **Coverage** is checked at review against the scenario inventory; the on-demand
   `tools/lint/spec_coverage.py` report parses Python bindings only, so TypeScript binding
   completeness and drift are a review judgment.

## Rationale

- TypeScript's structural typing catches shape errors but does not guarantee runtime behavior, and
  agents produce the same green-theater unit tests here as in any dynamic language. The generic
  behavioral model applies in full; this snippet fixes the TypeScript idioms that realize it.

## Scope

- All TypeScript code in this repository and in projects managed by this platform.

## Enforcement

- TypeScript spec bindings are checked at review; `tools/lint/spec_coverage.py` does not parse them.
- The reviewer rejects agent-authored unit tests.
- `tools/lint/forbid_ts_unit_tests.py` (pre-commit) structurally blocks agent-authored TypeScript
  unit tests, mirroring the Python ban's exit-code contract. It resolves the TypeScript surface from
  `frontend_root` in `teleclaude.yml` (default `frontend`), so a Next.js-only project where the
  package root is the app is covered by setting `frontend_root` to that root — no special-casing. Any
  tracked `*.test.ts(x)` under the resolved root that is co-located (e.g. in an `__tests__/`
  directory) or otherwise outside the doctrine path `<frontend_root>/tests/<domain>/<slug>.test.ts(x)`
  fails the commit. Playwright e2e specs (`*.spec.ts`) are functional and excluded by suffix.

## Exceptions

- None.
