---
description: 'Guidelines for AI agents to retrieve relevant documentation snippets on demand.'
visibility: 'public'
---

# Context Retrieval Policy — Policy

## Rules

- **Read a domain's baseline bundle once, at entry.** When a task enters a
  knowledge domain, read `~/.teleclaude/docs/<domain>/bundle.md` in full, as a
  file, unless its contracts are already loaded this session. A task enters
  `sdlc` when it writes or changes code or tests. The bundle is the domain's
  mandatory contract, pre-resolved for one pass; a procedure that always needs
  it names the bundle in its `## Required reads`. It is a generated artifact
  with no snippet id, so `telec docs get` does not serve it; its generation
  already leaves undelivered content out.
- **`telec docs` is the entry point for discovery, and always filtered.** Use
  `--areas`, `--domains`, and/or `--baseline-only`; an unfiltered index floods the
  context. Retrieve before any task where missing context could alter decisions.
- **Three phases:** filtered index, then `telec docs get <id>` for the selected
  ids, then the ids listed under `# Required reads (not loaded)` in that
  response. Dependencies are never expanded inline by default.
- **An activatable procedure's catalog instruction delivers its closure in one
  pass**, and a scheduled job's startup instruction does the same for the
  procedure its declaration names. Ordinary retrieval keeps the explicit
  follow-up flow.
- **Third-party docs: consolidated first.** Run `telec docs index --third-party`
  before web search or Context7; those are fallbacks for coverage gaps.

## Rationale

Immediate context prevents drift from established policy, architecture, and
procedure. Consolidated third-party docs are curated and project-aware; live web
results are noisy and bypass shared knowledge.

## Scope

All agents, all projects, all tasks.

## Enforcement

Reviewers treat domain work begun without the domain's contracts loaded as a
process miss; the remedy is to load them before continuing.

## Exceptions

None.
