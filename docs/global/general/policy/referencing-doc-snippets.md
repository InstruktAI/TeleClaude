---
description: 'Policy for referencing documentation snippets in AI agent prompts.'
id: 'general/policy/referencing-doc-snippets'
scope: 'global'
type: 'policy'
visibility: 'public'
---

# Referencing Doc Snippets — Policy

## Rules

- Use inline `@` references for all **required reads**.
- Global doc references must use the absolute-home form
  `@<HOME>/.teleclaude/docs/...` (e.g. `@/Users/alice/.teleclaude/docs/...`).
  This matches the enforced validator behavior at
  `teleclaude/resource_validation/_snippet.py:124` which expands
  `Path.home()` at validation time; the unexpanded `@~/...` literal
  is NOT accepted by the validator.
- Project doc references must use `@docs/...` (repo‑relative to the project root).
- Third-party sources must appear under **See also** only (soft references).
  They must not appear in Required reads.

## Rationale

- Inline `@` references are the single enforced mechanism for mandatory reading.
- A stable global root (`~/.teleclaude/docs`, written as the absolute-
  home form `<HOME>/.teleclaude/docs/...`) prevents ambiguity across
  repos. The validator expands `Path.home()` per-machine, so refs
  remain machine-local but consistent within one operator's environment.
- Repo‑relative `@docs/...` keeps project docs portable and consistent.
- Soft references prevent third-party docs from being auto-included in agent context.

## Scope

- Applies to all AI agents, all repositories, and all documentation used for AI prompting.
- Applies to `AGENTS.md`, baseline indexes, and any doc snippet that requires prerequisites.

## Enforcement

- Required reads must appear in a `Required reads` section immediately after the H1 title (or after the activation line in commands/agents).
- Required reads must use inline `@` references only.
- Soft references must appear in a `See also` section at the bottom and must not use `@`.

## Exceptions

- None.

## See Also

- ~/.teleclaude/docs/general/procedure/agent-artifact-authoring.md
