---
description:
  Ten-step sequence for producing cohesive, atomic docs without losing
  context.
id: software-development/procedure/snippet-authoring-sequence
scope: domain
type: procedure
---

# Snippet Authoring Sequence (10 Steps)

Authoring is performed by AI. Write snippets for AI execution and maintenance, while remaining clear to humans.

1. **Define intent first** — pick one taxonomy type and a single responsibility.
2. **Find the smallest complete unit** — it must stand alone without hidden dependencies.
3. **Preserve cohesion** — keep coupled rules and constraints together.
4. **Split only on true separability** — split only when parts are independently usable.
5. **Choose domain-first placement** — mirror the repo’s business model in folder structure.
6. **Write frontmatter** — `id`, `type`, `scope`, `description`, `requires` (if needed).
7. **Decide inclusion** — use `@path` to require the AI to read a dependency; use `requires` to declare dependency relationships for selection.
8. **Use type-specific structure** — procedures are steps, policies are rules, references are structured lookups.
9. **Minimize the body** — include only what is required to act correctly.
10. **Validate against reality** — ensure alignment with code, process, and system behavior.
11. **Rebuild and validate** — run `~/.teleclaude/scripts/build_snippet_index.py`, which regenerates indexes automatically.

See also

- Place soft references in a bottom section named `See also` to avoid forced inclusion.
- If a point is already a hard requirement, omit the reference; if it is optional guidance, reference without `@`.
