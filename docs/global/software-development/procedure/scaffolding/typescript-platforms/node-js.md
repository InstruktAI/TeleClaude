---
description: 'Node.js/CLI scaffolding guidance: framework-neutral services and command-line tools with native ESM.'
visibility: 'public'
---

# TypeScript Node.js Scaffolding — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/scaffolding/typescript.md

## Goal

Scaffold a framework-neutral Node.js service or CLI with native ESM.

## Preconditions

- Portfolio fit: glue services and CLIs. Public HTTP APIs prefer the Hono
  flavor; long-running unattended daemons prefer Rust.
- Check current Node LTS and its native TypeScript execution status.

## Steps

1. Native ESM throughout; strict TypeScript per the base.
2. Framework-neutral repo → Biome as the single lint+format tool.
3. `tsx` (or Node's native type-stripping when stable) for the dev runner.
4. CLIs ship proper exit codes and `--help`; services ship typed env/config
   and structured logging.
5. Wire the standard buttons and CI.

## Outputs

- A Node.js ESM repo with buttons and CI wired.

## Recovery

- If the service turns out to be a public API or a daemon, reclassify to the
  Hono or Rust flavor before growing further.

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
