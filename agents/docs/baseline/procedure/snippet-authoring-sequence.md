# Snippet Authoring Sequence (10 Steps) — Procedure

## Required reads

- @~/.teleclaude/docs/baseline/policy/referencing-doc-snippets.md

## Goal

Concise clear documentation snippets that are easy for AI agents to consume and act upon.

## Rules

1. **Define intent first** — pick one taxonomy type and a single responsibility.
2. **Find the smallest complete unit** — it must stand alone without hidden dependencies.
3. **Preserve cohesion** — keep coupled rules and constraints together.
4. **Split only on true separability** — split only when parts are independently usable.
5. **Choose domain-first placement** — mirror the repo’s business model in folder structure.
6. **Write frontmatter** — `id`, `type`, `scope`, `description`.
7. **Required reads first** — start with a `Required reads` section at the top and list hard dependencies with `@` references.
8. **Use type-specific structure** — procedures are steps, policies are rules, references are structured lookups.
9. **Minimize the body** — include only what is required to act correctly.
10. **See also last** — end with a `See also` section for soft references without `@`.
11. **Validate against reality** — ensure alignment with code, process, and system behavior.

## Rationale

- A clear sequence ensures consistency and quality across all snippets.
- Following taxonomy-specific structures aids AI discovery, comprehension and usability.
- Explicit dependencies prevent runtime failures due to missing context.
- Enforcing required reads upfront guarantees prerequisite knowledge is acquired.
- Type-specific structures optimize for the intended use case and improve clarity.

## Scope

- Applies to all documentation snippets authored for AI agents.
- Covers all taxonomy types: Principles, Architecture, Policy, Procedure, Reference.
- Encompasses both global and project-specific documentation.

## Enforcement

- Snippets must follow the 10-step authoring sequence.
- Required reads must be listed at the top using inline `@` references.
- Body structure must align with the chosen taxonomy type.
- Snippets will be reviewed for adherence to these rules before acceptance.

## Exceptions or edge cases

- None. All snippets must comply with the authoring sequence to ensure quality and usability.
