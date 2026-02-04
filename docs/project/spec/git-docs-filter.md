---
id: project/spec/git-docs-filter
type: spec
scope: project
description: Git filter that expands tilde paths for agents and normalizes them for portable commits.
---

# Git Docs Filter — Spec

## What it is

The `teleclaude-docs` git filter ensures doc `@` references work for both agents and version control:

- **Smudge** (on checkout): expands `@~/.teleclaude` to the local absolute path (e.g., `@/Users/mo/.teleclaude`). Agents resolve absolute paths reliably; tilde paths cause lookup failures.
- **Clean** (on commit): normalizes local absolute paths back to `@~/.teleclaude` so commits remain portable across machines.

Configured via `.gitattributes` on all `docs/**/*.md`, `agents/docs/**/*.md`, and `docs/*/index.yaml` files.

## Canonical fields

- **Filter name**: `teleclaude-docs`
- **Smudge command**: `sed "s|@~/.teleclaude|@{home}/.teleclaude|g"`
- **Clean command**: reverse substitution back to `@~/.teleclaude`
- **Required**: `true` (git will refuse to checkout if filter is missing)
- **Setup**: `telec init` configures the filter in local git config

## Allowed values

- Only `@~/.teleclaude` paths are stored in commits.
- Only absolute paths appear in working copies.

## Known caveats

- If the filter is not configured locally (missing `telec init`), commits may capture absolute paths and a pre-commit hook will reject them.
- If the local home path changes, re-run `telec init` to reconfigure the filter.
- The filter lives in local git config, not in `.gitconfig` — each clone needs initialization.
