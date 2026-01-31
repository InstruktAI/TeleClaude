# Referencing Doc Snippets Policy — Policy

## Rules

- Use inline `@` references for all **required reads**.
- Global doc references must use `@~/.teleclaude/docs/...`.
- Project doc references must use `@docs/...` (repo‑relative to the project root).

## Rationale

- Inline `@` references are the single enforced mechanism for mandatory reading.
- A stable global root (`~/.teleclaude/docs`) prevents ambiguity across repos.
- Repo‑relative `@docs/...` keeps project docs portable and consistent.

## Scope

- Applies to all AI agents, all repositories, and all documentation used for AI prompting.
- Applies to `AGENTS.md`, baseline indexes, and any doc snippet that requires prerequisites.

## Enforcement

- Required reads must appear in a `Required reads` section at the top of the document.
- Required reads must use inline `@` references only.
- Soft references must appear in a `See also` section at the bottom and must not use `@`.

## Exceptions

- None.
