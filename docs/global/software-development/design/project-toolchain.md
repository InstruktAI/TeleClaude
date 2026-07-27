---
description: "TeleClaude offers shared telec code functionality that runs each project's own language-agnostic Makefile; the project owns its toolchain, telec orchestrates and scopes."
visibility: 'public'
---

# Project Toolchain Integration — Design

## Purpose

TeleClaude offers shared functionality — the `telec code` commands, the checkpoint
engine, the blessed default configs — that runs on each adopted project's **own**
machinery (its `Makefile`, configs, tools). Nothing is copied into the project. **The
only thing the platform mandates is the `Makefile`** (the operational plug); every
tool and config behind it is detected and plugged onto, never prescribed. A project
stays installable and testable with no TeleClaude present; TeleClaude adds workspace
scoping, agent-facing simplification, and _offered_ best-practice defaults on top of
what the project already wires up.

## Inputs/Outputs

**The project owns** a language-agnostic `Makefile` whose targets run whatever
toolchains are present, plus the per-language configs and manifests:

| Target         | Does                                                                                                                                                                                   | Scoped?        |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| `make install` | provisions every present toolchain: `uv sync` (python); corepack + lockfile-detected package manager (pnpm/npm/yarn/bun) + frozen install (node, incl. frontend); `cargo fetch` (rust) | no             |
| `make lint`    | lints whatever is present, on the `FILES_FROM` path set or all                                                                                                                         | yes — required |

<!-- planned-change:scope-worktree-build-gate-to-own-tests -->

| `make test` | runs every suite present (python + frontend + rust) | no — there is no 1:1 source→test map |

<!-- change:scope-worktree-build-gate-to-own-tests -->

| `make test` | runs every suite present (python + frontend + rust), on the `FILES_FROM` test-file set or all | yes — test files only |

<!-- /planned-change:scope-worktree-build-gate-to-own-tests -->

| `make format` | formats whatever is present, on the `FILES_FROM` path set or all | yes — required |

**Blessed defaults** — configs the platform _offers_ (never prescribes) to seed a
greenfield setup or raise a brownfield one that is missing or weaker. The agent
detects what a project uses and plugs it onto the `Makefile`; the steward offers a
default where it helps. Tools are never mandated.

- **Python** — uv · ruff / pyright / mypy · pytest
- **TypeScript / node** — pnpm · tsc (typecheck) · vitest (test) · and a linter/formatter the agent picks by heuristic: **ESLint + Prettier** for Next.js/React (framework + React-Compiler lints) or **Biome** for framework-agnostic projects — both shipped as defaults. Frontend deps via corepack + lockfile-detected manager.
- **Rust** — cargo fmt / clippy / test

**TeleClaude offers, never copies in:** the `telec code` orchestration layer, agent
instructions (the checkpoint), and the offered skeleton defaults (the steward).

**Recipes delegate; they carry no inline logic.** A `Makefile` target is a thin
convention name: its recipe is a single delegation to a script or typed module
entrypoint that owns the behavior (a `tools/`/`bin/` bash script when it only
shells out to binaries, a module entrypoint when it earns a test). In
TeleClaude's own repo this admits no exception — direct single-tool invocations,
status output, and multi-step bodies all live behind the delegated script or
module, never inline. Satellites are offered the convention, never mandated — see
`software-development/policy/no-inline-logic`, which governs every file that can
carry an executable body.

## Invariants

1. The `Makefile` (`install` / `test` / `lint` / `format`) is the **only** thing the
   platform mandates; the tools and configs behind those targets are detected and
   offered, never prescribed.
2. TeleClaude tooling is never copied into a project; a project invokes the shared
   `telec code` commands, which act on the project's own machinery.
3. A project remains installable and testable standalone via its own `make` targets,
   with no TeleClaude present.
4. `telec code` only ever runs the project's own configured tools / make targets; it
   embeds no toolchain of its own (beyond TeleClaude-flavored policy checks layered on
   top where TeleClaude is present).
5. `make install` is the prerequisite for `telec code`; `telec code install` defers to
   it.

<!-- planned-change:scope-worktree-build-gate-to-own-tests -->

6. `make test` is never file-scoped — the spec-anchored model has no 1:1 source→test
   map.

<!-- change:scope-worktree-build-gate-to-own-tests -->

6. `make test` scopes to **test files only**. The spec-anchored model has no 1:1
   source→test map, so a `FILES_FROM` set never selects tests from the source files
   that changed — it carries the test files themselves, and the recipe routes each to
   the tier that owns it. A scoped set that yields no executable test fails; an
   unscoped run is the full suite, unchanged.

<!-- /planned-change:scope-worktree-build-gate-to-own-tests -->

## Primary flows

`telec code` is the scoping / orchestration layer; it delegates execution to the
project's `make`:

- `telec code install` → `make install` (the install prerequisite).
- `telec code lint` → resolve workspace scope → `make lint FILES_FROM=<tmpfile>`.

<!-- planned-change:scope-worktree-build-gate-to-own-tests -->

- `telec code test` → `make test` (unscoped).

<!-- change:scope-worktree-build-gate-to-own-tests -->

- `telec code test` → `make test` (unscoped), or `make test FILES_FROM=<tmpfile>` when
  test-file operands are declared.

<!-- /planned-change:scope-worktree-build-gate-to-own-tests -->

- `telec code format` → `make format FILES_FROM=<tmpfile>` (unscoped only when no scope resolves).

Workspace scoping (which files are in play for this session/worktree) is resolved by
`telec code` per `software-development/design/workspace-scoping`, then handed to
`make lint` and `make format` as `FILES_FROM` — the path to a temp file holding the
scoped paths, **NUL-terminated**. The paths never travel on `make`'s command line, in
`$@`/`$*`, or as a make goal; `FILES_FROM` is the only scope channel. Honoring it is
required. A recipe that ignores it, or that treats an unreadable `FILES_FROM` as
unscoped, lints the whole tree and violates
`software-development/design/workspace-scoping` invariant 3. TeleClaude-flavored policy
checks (guardrails, snapshot-testing) layer on top of the project's own linters where
TeleClaude is present.

<!-- planned:scope-worktree-build-gate-to-own-tests -->

`make test` uses the same `FILES_FROM` channel with the same NUL-terminated encoding,
but a different scope source: the set is the test files a caller declares — the branch's
own touched test files for the worktree build gate, or explicit operands for
`telec code test` — never a workspace-scoped source set.

<!-- /planned:scope-worktree-build-gate-to-own-tests -->

## Failure modes

- **No Makefile / missing target.** `telec code <verb>` has nothing to delegate to —
  it reports the missing target and points at the steward
  (`software-development/procedure/code-config-assessment`) to wire it up.
- **Toolchain not installed.** `make install` (or `telec code install`, which the
  checkpoint flags when a package manifest changes on main) provisions it. A project
  that runs `make test` before `make install` fails on missing binaries — that is the
  prerequisite ordering, surfaced by the checkpoint flag, not a defect in the runner.
- **Project diverges from a default.** The steward raises the floor and respects the
  ceiling: it offers a default where the project is **missing or weaker**, leaves
  **deliberate, project-owned** config untouched, and asks the human only on a genuine
  conflict — never silently overwrites intent.
