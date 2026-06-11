---
description: 'AI-safe telec CLI commands for project work, docs sync, todo scaffolding, and configuration.'
visibility: 'public'
---

# Telec CLI Tool — Spec

## What it is

AI-safe `telec` commands for project work. Run `telec <subcommand> --help` for details on any subcommand.

> **Source:** `teleclaude/cli/telec.py` — edit `CLI_SURFACE` dict and `CommandDef` entries to change commands, descriptions, and flags.

## Canonical fields

Pending `revive-todo-update-command`, the todo mutation surface includes
`telec todo update <slug> [--slug <new>] [--after <dep>]... [--kind <kind>]
[--force]` and no longer includes public `telec todo rename` or
`telec todo set-deps` verbs. The command table below is generated from the CLI
surface and will reflect this when the delivering code updates
`teleclaude/cli/telec/surface.py` and `telec sync` runs.

There are many of course, but this section is now intended to reveal the full surface of baseline commands that we want you to know out of the box.

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

Rust is a first-class `telec code` language when `rust` is declared in
`teleclaude.yml`. `telec code lint`, `telec code format`, and `telec code test`
invoke Cargo tooling from the Cargo workspace root. Single-crate Rust changes
use `-p <package>` where Cargo supports package scoping; cross-crate changes,
root Cargo metadata changes, and `--all` use workspace scope.

`telec code commit` remains decoupled from the dev-time Rust pipeline. Commit-time
Rust gates are owned by the existing pre-commit cargo hooks. The current Rust
test hook is library-only (`cargo test --workspace --lib --quiet`) unless a
future task changes the hook.

<!-- planned:telec-code-delegates-to-make -->
`telec code` is the scoping + composition layer. `telec code lint` resolves
workspace scope and runs **two decoupled legs**: (1) the project's own `make
lint` — native tools only, zero TeleClaude dependency — receiving the scoped
file list as a NUL-delimited `FILES_FROM` temp file (paths never travel on the
command line); and (2) TeleClaude's **guardrails lane** (the policy checks) over
the same scoped files. It exits non-zero if either leg fails; a full run (no
`FILES_FROM`) happens on `--all`, CI, or a no-session shared branch. `telec code
test` runs `make test` (unscoped); `telec code format` runs `make format`;
`telec code install` runs `make install`. The project's `Makefile` owns only the
native toolchain and never contains guardrails or `telec`; the guardrails lane
is TeleClaude's and is never plumbed into any `Makefile`. There is no `--step`
flag and no guardrails subcommand — guardrails run only as the second leg of
`telec code lint`.
<!-- /planned:telec-code-delegates-to-make -->

