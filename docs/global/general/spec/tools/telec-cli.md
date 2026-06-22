---
description: 'AI-safe telec CLI commands for project work, docs sync, todo scaffolding, and configuration.'
visibility: 'public'
---

# Telec CLI Tool — Spec

## What it is

AI-safe `telec` commands for project work. Run `telec <subcommand> --help` for details on any subcommand.

> **Source:** `teleclaude/cli/telec.py` — edit `CLI_SURFACE` dict and `CommandDef` entries to change commands, descriptions, and flags.

## Canonical fields

The command table below is generated from the live CLI surface (`CLI_SURFACE`
in `teleclaude/cli/telec/surface.py`) and re-rendered into this baseline doc on
every `telec sync`, so it always reflects the current surface. It reveals the
full set of baseline commands every agent should know out of the box.

<!-- @exec: telec -h -->

The surface table above shows every command's full argument signature. For
commands not detailed below, run `telec <subcommand> --help` on demand — the
full surface is already in your context.

The blocks below are the few subcommands whose `--help` carries behavioral
information (footguns, gate semantics, multi-step flow) you cannot infer from
the signature alone.

### `telec sessions run`

<!-- @exec: telec sessions run -h -->

### `telec sessions send`

<!-- @exec: telec sessions send -h -->

### `telec docs`

<!-- @exec: telec docs -h -->

### `telec code`

<!-- @exec: telec code -h -->

`telec code` is the scoping + composition layer; it embeds no toolchain of its
own. `telec code lint` resolves workspace scope. A scoped (interactive) run first
applies `make format` over those paths — a best-effort fix+format whose result
the developer sees and commits — then runs **two decoupled legs**: (1) the
project's own `make lint` — native tools only (ruff/pyright/mypy/jscpd,
eslint/tsc, cargo), zero TeleClaude dependency — receiving the scoped file list
as a NUL-delimited `FILES_FROM` temp file (paths never travel on the command
line); and (2) TeleClaude's **guardrails lane** (the policy checks) over the same
scoped paths. It exits non-zero if either leg fails. The full run (no
`FILES_FROM`) happens on `--all`, CI, or a no-session shared branch; it never
formats and stays check-only. `telec code test
[--update-snapshots]` runs `make test` (unscoped; snapshot-update forwarded);
`telec code format [<files>]` runs `make format` (scoped to the files when
given); `telec code install` runs `make install`. There is no `--step` flag and
no guardrails subcommand — guardrails run only as the second leg of `telec code
lint`.

The project's `Makefile` owns the entire native toolchain and never contains
guardrails or `telec`; the guardrails lane is TeleClaude's and is never plumbed
into any `Makefile`. The native Makefile contract is identical for TeleClaude's
own repo and any adopting project — a project stays installable and lintable
standalone via `make`. The current guardrails lane is TeleClaude-repo-rooted.

Native language support behind `make`: Rust is a first-class language when
`rust` is declared in `teleclaude.yml` — the project's `make lint`/`format`/`test`
recipes invoke Cargo tooling from the Cargo workspace root (single-crate changes
may use `-p <package>`; cross-crate and full runs use workspace scope). `telec
code` selects which files are in scope and delegates; it does not invoke Cargo
itself.

`telec code commit` runs format then lint in-process against `quality_paths`
(the commit pathspec filtered to existing files) before `git commit --no-verify`.
No framework stash, no working-tree reset outside the pathspec. The installed
`.git/hooks/pre-commit` is a thin telec-owned guard that performs only a
partial-staging check as a backstop for raw `git commit` invocations.

<!-- planned:distributed-todo-postgres -->

`telec code commit` is the single commit+push front door for both worktree lanes.
After a successful worktree commit, under the main-branch lock, it auto-pushes
through the shared git transport gateway with the target resolved from the
worktree: a feature worktree (`trees/<slug>`, branch == slug) pushes
`HEAD:<slug>`; the integration worktree (`trees/_integration`, detached) pushes
`HEAD:main`. Build commits therefore push per-commit rather than accumulating
until finalize, so git carries in-progress work across machines. The command's
exit status reflects the commit; the push result is reported separately as a
closed-vocabulary, agent-readable outcome — `ok | superseded | transient |
blocked | skipped_no_remote`. `superseded` is a dead fork (stop); `transient`
syncs on the next push (push is cumulative, no retry queue); `blocked` escalates;
`skipped_no_remote` is the expected silent no-op for a local-only project. Stack
traces are never surfaced as control flow.

<!-- /planned:distributed-todo-postgres -->

## Known caveats

- Removing or renaming a subcommand is a breaking change.
- Changing argument order or required flags is a breaking change.
- Adding a subcommand is a feature addition.
- Description-only changes are patches.
