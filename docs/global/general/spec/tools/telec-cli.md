---
description: 'AI-safe telec CLI commands for project work, docs sync, todo scaffolding, and configuration.'
visibility: 'public'
---

# Telec CLI Tool — Spec

## What it is

AI-safe `telec` commands for project work. Run `telec <subcommand> --help` for details on any subcommand.

> **Source:** `teleclaude/cli/telec.py` — edit `CLI_SURFACE` dict and `CommandDef` entries to change commands, descriptions, and flags.

WHAT THIS DOCOMENT IS NOT: its not a document to add design to, as this document is merely the baseline inclusion listing the cli commands, with some subcommands expanded as they get used a lot. Agents are NOT to modify this file unless more explicit expansion of subcommands is needed.

## Canonical fields

The command table below is generated from the live CLI surface (`CLI_SURFACE`
in `teleclaude/cli/telec/surface.py`) and re-rendered into this baseline doc on
every commit to the cli or this doc, so it always reflects the current surface. It reveals the
full set of baseline commands every agent should know out of the box:

<!-- @exec: telec -h -->

The surface table above shows every command's full argument signature. For
commands not detailed below, run `telec <subcommand> --help` on demand — the
full surface is already in your context.

The blocks below are the few subcommands whose `--help` carries behavioral
information (footguns, gate semantics, multi-step flow) you cannot infer from
the signature alone, or which are used frequently enough to warrant a quick reference.

### `telec sessions run`

<!-- @exec: telec sessions run -h -->

### `telec sessions send`

<!-- @exec: telec sessions send -h -->

### `telec sessions end`

With an explicit session id, the command ends that session; `self` retains its
existing self-termination meaning. With no target, the command requires a live
caller identity and closes every live direct child of that caller across
computers. The caller-scoped form is idempotent when empty and returns success
only after no direct child remains; a residual child is a command failure.

### `telec docs`

<!-- @exec: telec docs -h -->

### `telec code`

<!-- @exec: telec code -h -->

## Known caveats

- Removing or renaming a subcommand is a breaking change.
- Changing argument order or required flags is a breaking change.
- Adding a subcommand is a feature addition.
- Description-only changes are patches.
- Every command recognizes exactly the options its usage line and option list
  declare, including every declared short alias. An undeclared option is
  rejected with that command's usage and a non-zero exit status; `--` ends
  option parsing; `--option=value` is accepted for value-taking options.
  Historical conversation search is the one command that accepts undeclared
  dash-leading tokens, as search text.
- `telec todo create --approved` (unless `--icebox` or `--hold` is also
  supplied) hands the todo to the coordinator's automatic dispatch the moment
  it prints `Created todo: <slug>`. The creating agent's involvement ends at
  that call — it does not offer, ask about, or narrate further action on that
  todo afterward; preparation and build are the coordinator's to initiate, not
  the caller's.
