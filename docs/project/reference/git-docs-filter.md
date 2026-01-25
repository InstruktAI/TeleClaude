---
id: reference/git-docs-filter
type: reference
scope: project
description: Git filter that normalizes doc paths for local use and portable commits.
---

# Git Docs Filter — Reference

## What it is

The `teleclaude-docs` git filter normalizes doc paths so:

- Working copies use local absolute paths for convenience.
- Commits remain portable by storing `@~/.teleclaude/...` paths.

This filter applies to docs and index files via `.gitattributes`.

## Canonical fields

- **Filter name**: `teleclaude-docs`
- **Smudge**: replace `@~/.teleclaude` with the local absolute path
- **Clean**: replace local absolute path with `@~/.teleclaude`
- **Applies to**: docs markdown and docs index YAML

## Allowed values

- None.

## Known caveats

- If the filter is missing locally, commits may capture absolute paths.
- If the local home path changes, re-run doc tooling to re-normalize.
- The filter is configured in the repository git config (not in the docs).
