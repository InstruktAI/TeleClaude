# Command Schema — Reference

Required reads

@~/.teleclaude/docs/baseline/reference/agent-artifacts.md

## What it is

A command is a user-invoked slash command defined in `commands/<name>.md`.
Commands are discovered by runtimes and exposed to users.

## Canonical fields

Frontmatter (YAML):

- `name` (string, required)
  - The slash command handle (without leading slash).
- `description` (string, required)
  - What the command does and when to use it.
- `version` (string, optional)
  - Semantic version for change tracking.
- `usage` (string, optional)
  - Short usage string, e.g. `my_command --flag value`.

Body:

- Behavior, parameters, and output expectations.

## Field intent and authoring rules

- `name` must be stable and match the file name.
- `description` should be a one-line action summary.
- `usage` should be short and copyable.

## Discovery behavior

- Runtimes scan `commands/` for `*.md` files.
- Frontmatter determines visibility and help text.

## Known caveats

- Keep commands deterministic; avoid side effects unless stated.
- If a command is complex, link to a reference doc instead of embedding it.
