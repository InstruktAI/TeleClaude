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

Rust is a first-class `telec code` language when `rust` is declared in
`teleclaude.yml`. `telec code lint`, `telec code format`, and `telec code test`
invoke Cargo tooling from the Cargo workspace root. Single-crate Rust changes
use `-p <package>` where Cargo supports package scoping; cross-crate changes,
root Cargo metadata changes, and `--all` use workspace scope.

`telec code commit` is decoupled from the dev-time Rust pipeline. Commit-time
Rust gates are owned by the pre-commit cargo hooks. The Rust test hook is
library-only (`cargo test --workspace --lib --quiet`).

## Known caveats

- Removing or renaming a subcommand is a breaking change.
- Changing argument order or required flags is a breaking change.
- Adding a subcommand is a feature addition.
- Description-only changes are patches.

