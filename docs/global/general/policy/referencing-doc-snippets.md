---
description: 'Policy for referencing documentation snippets in AI agent prompts.'
visibility: 'public'
---

# Referencing Doc Snippets — Policy

## Rules

- Use inline `@` references only for **static Required reads declarations** in published agent artifacts and documentation snippets. They are expanded when those artifacts are assembled.
- Runtime-generated briefs, formatter messages, and peer messages must never use inline `@` references. Name the canonical snippet ID and, when needed, the `telec docs get <id>` invocation instead. Expanding a reference into an already-running session duplicates context and bypasses that session's own required-read discipline.
- Global doc references must use the absolute-home form
  `@<HOME>/.teleclaude/docs/...` (e.g. `@<HOME>/.teleclaude/docs/...`).
  This matches the enforced validator behavior at
  `teleclaude/resource_validation/_snippet.py:124` which expands
  `Path.home()` at validation time; the unexpanded `@~/...` literal
  is NOT accepted by the validator.
- A published domain's generated baseline bundle is a valid global Required Read at
  `@<HOME>/.teleclaude/docs/<domain>/domain-baseline-bundle.md`. This exact generated-artifact
  shape is the sole exception to the taxonomy-segment requirement. Validation accepts it only
  for a published domain, and deploy mode generates it before agent-artifact transpilation.
- Project doc references must use `@docs/...` (repo‑relative to the project root).
- Third-party sources must appear under **See also** only (soft references).
  They must not appear in Required reads.

## Rationale

- Inline `@` references are the single enforced mechanism for mandatory reading declared by a static artifact. Runtime instructions name the required snippet without expanding it so the receiving session controls the read once.
- A stable global root (`~/.teleclaude/docs`, written as the absolute-
  home form `<HOME>/.teleclaude/docs/...`) prevents ambiguity across
  repos. The validator expands `Path.home()` per-machine, so refs
  remain machine-local but consistent within one operator's environment.
- Repo‑relative `@docs/...` keeps project docs portable and consistent.
- Soft references prevent third-party docs from being auto-included in agent context.

## Scope

- Applies to all AI agents, all repositories, and all documentation references in static artifacts or runtime messages.
- Static-declaration rules apply to `AGENTS.md`, baseline indexes, commands, agents, and any doc snippet that requires prerequisites.

## Enforcement

- Static Required reads must appear in a `Required reads` section immediately after the H1 title (or after the activation line in commands/agents).
- Static Required reads must use inline `@` references only.
- Runtime formatter and peer-message output containing an inline `@` documentation reference is a defect.
- Soft references must appear in a `See also` section at the bottom and must not use `@`.

## Exceptions

- None.

## See Also

- ~/.teleclaude/docs/general/procedure/agent-artifact-authoring.md
