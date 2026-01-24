# Agent Schema

Required reads

@~/.teleclaude/docs/baseline/reference/agent-artifacts.md

## What it is

An agent is a specialized helper defined in `agents/<name>.md`. It is discovered
by agent runtimes and can be selected based on its metadata and description.

## Canonical fields

Frontmatter (YAML):

- `name` (string, required)
  - Human-readable agent name. Keep stable; changing it breaks recognition.
- `description` (string, required)
  - Primary selector text. Must state **when to use** the agent.
- `version` (string, optional)
  - Semantic version for change tracking.
- `capabilities` (array of strings, optional)
  - Short verb phrases that describe concrete tasks the agent can perform.

Body:

- Role intent, constraints, and execution guidance.

## Field intent and authoring rules

- `description` must be **action-oriented** and **selection-friendly**.
  - Good: "Use to review Python changes for correctness and edge cases."
  - Bad: "A helpful agent for many tasks."
- `capabilities` should be **verbs**, not nouns.
  - Good: ["review", "test", "refactor"]
  - Bad: ["code", "quality", "python"]
- `name` should be **stable and short**; avoid marketing language.

## Discovery behavior

- Runtimes scan `agents/` for `*.md` files.
- Frontmatter fields are used for matching and selection.
- Missing or vague metadata reduces agent discoverability.

## Known caveats

- Keep agents narrow; prefer multiple focused agents to one generalist.
- Do not embed long tutorials; link to references instead.
