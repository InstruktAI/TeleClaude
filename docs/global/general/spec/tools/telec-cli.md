---
id: 'general/spec/tools/telec-cli'
type: 'spec'
scope: 'global'
description: 'AI-safe telec CLI commands for project work, docs sync, todo scaffolding, and configuration.'
---

# Telec CLI Tool — Spec

## What it is

AI-safe `telec` commands for project work. Run `telec <subcommand> --help` for details on any subcommand.

> **Source:** `teleclaude/cli/telec.py` — edit `CLI_SURFACE` dict and `CommandDef` entries to change commands, descriptions, and flags.

## Canonical fields

There are many of course, but this section is now intended to reveal the full surface of baseline commands that we want you to know out of the box.

<!-- @exec: telec -h -->

### `telec docs`

<!-- @exec: telec docs -h -->

