---
id: 'project/spec/git-docs-filter'
type: 'spec'
scope: 'project'
description: 'Git filter that expands tilde paths for agents and normalizes them for portable commits.'
---

# Git Docs Filter — Spec

## What it is

The `teleclaude-docs` git filter ensures doc references and index paths work for both agents and version control:

- **Smudge** (on checkout): expands `/Users/Morriz/.teleclaude` to the local absolute path (e.g., `/Users/mo/.teleclaude`). Agents resolve absolute paths reliably; tilde paths cause lookup failures. Matches `@`-prefixed references in `.md` files.
- **Clean** (on commit): normalizes local absolute paths back to `/Users/Morriz/.teleclaude` so commits remain portable across machines.

Configured via `.gitattributes` on all `docs/**/*.md` and `agents/docs/**/*.md` files.

## Canonical fields

- **Filter name**: `teleclaude-docs`
- **Smudge command**: `sed "s|/Users/Morriz/.teleclaude|{home}/.teleclaude|g"`
- **Clean command**: `sed "s|{home}/.teleclaude|/Users/Morriz/.teleclaude|g"`
- **Required**: `true` (git will refuse to checkout if filter is missing)
- **Setup**: `telec projects init` configures the filter in local git config

## Allowed values

- Only `/Users/Morriz/.teleclaude` paths are stored in commits.
- Only absolute paths appear in working copies.

## Known caveats

- If the filter is not configured locally (missing `telec projects init`), commits may capture absolute paths and a pre-commit hook will reject them.
- If the local home path changes, re-run `telec projects init` to reconfigure the filter.
- The filter lives in local git config, not in `.gitconfig` — each clone needs initialization.
