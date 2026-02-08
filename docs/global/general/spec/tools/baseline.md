---
id: 'general/spec/tools/baseline'
type: 'spec'
scope: 'global'
description: 'Progressive-disclosure entrypoint for the global tool cabinet.'
---

# Tools Baseline — Spec

## Required reads

@~/.teleclaude/docs/general/spec/tools/history-search.md
@~/.teleclaude/docs/general/spec/tools/agent-restart.md
@~/.teleclaude/docs/general/spec/tools/memory-management-api.md

## What it is

Defines the baseline loading surface for tool specs so agents receive a minimal tool cabinet by default and can expand details on demand.

## Canonical fields

- Cabinet scope: global tools available across agent runtimes.
- Baseline members:
  - `general/spec/tools/history-search`
  - `general/spec/tools/agent-restart`
  - `general/spec/tools/memory-management-api`

## Allowed values

- Members are snippet IDs under `general/spec/tools/*` only.

## Known caveats

- Keep this baseline small; add only high-frequency tool primitives.
- Move low-frequency or specialized tools to on-demand specs outside baseline membership.
