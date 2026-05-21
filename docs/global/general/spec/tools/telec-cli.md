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
