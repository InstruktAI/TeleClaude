---
description: 'Git filter that expands tilde paths for agents and normalizes them for portable commits.'
visibility: 'public'
---

# Git Docs Filter — Spec

## What it is

The `teleclaude-docs` git filter ensures doc references and index paths work for both agents and version control:

- **Smudge** (on checkout): expands `@~/.teleclaude` to the local absolute `@$HOME/.teleclaude`. Agents resolve absolute paths reliably; tilde paths cause lookup failures. Matches `@`-prefixed references in `.md` files only.
- **Clean** (on commit): normalizes the local absolute form `@$HOME/.teleclaude` back to the portable `@~/.teleclaude` so commits remain portable across machines.

Configured via `.gitattributes` on all `docs/**/*.md` and `agents/docs/**/*.md` files.

## Canonical fields

- **Filter name**: `teleclaude-docs`
- **Smudge command**: `sed "s|@~/.teleclaude|@$HOME/.teleclaude|g"`
- **Clean command**: `sed "s|@$HOME/.teleclaude|@~/.teleclaude|g"`
- **Required**: `true` (git will refuse to checkout if filter is missing)
- **Setup**: `telec projects init` configures the filter in local git config

## Allowed values

- Only the portable form `@~/.teleclaude` is stored in commits.
- Only the local absolute form `@$HOME/.teleclaude` appears in working copies.
- The `@` marker is what triggers normalization; bare `~/.teleclaude` references are not rewritten.

## Known caveats

- If the filter is not configured locally (missing `telec projects init`), commits may capture absolute paths and a pre-commit hook will reject them.
- If the local home path changes, re-run `telec projects init` to reconfigure the filter.
- The filter lives in local git config, not in `.gitconfig` — each clone needs initialization.
