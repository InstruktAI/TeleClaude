---
description: 'AI-safe telec CLI commands for project work, docs sync, todo scaffolding, and configuration.'
id: 'general/spec/tools/telec-cli'
scope: 'global'
type: 'spec'
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
`telec code lint|test|format|install` are thin scoping shims: each resolves
workspace scope and delegates to the project's own `make` target. `telec code
lint` resolves scope and invokes `make lint`, passing the scoped file list as a
NUL-delimited `FILES_FROM` temp file (paths never travel on the command line); a
full `make lint` with no `FILES_FROM` runs on `--all`, CI, or a no-session
shared branch. `telec code test` runs `make test` (unscoped); `telec code
format` runs `make format`; `telec code install` runs `make install`. The
project's `Makefile` owns the toolchain — native tools plus any repo-local
policy scripts — and runs with zero TeleClaude dependency; `telec code` embeds
no tool of its own and only serializes the resolved file scope into the
`FILES_FROM` file. There is no `--step` flag and no guardrails subcommand:
guardrails run as a repo-local lint step behind `make lint`, never as a `telec`
command.
<!-- /planned:telec-code-delegates-to-make -->

