# Conflict Resolution Rules

Sources that can conflict:

- Baseline docs, domain docs, project docs
- Repo docs (`README.md`, `AGENTS.md`, `docs/**`)
- Code comments and docstrings
- Tooling conventions or generated artifacts

Common conflict types:

- Scope mismatch (global guidance vs project-specific constraints)
- Framework specificity (generic scaffolding vs framework-specific instructions)
- Policy vs procedure (what must hold vs how to do it)
- Docs vs code (documentation lags behind actual behavior)

When guidance conflicts, resolve in this order:

1. **Prefer more specific scope over less specific**
   - Project > Domain > Global

2. **Prefer framework-specific scaffolding over generic scaffolding**
   - Use generic scaffolding only when no framework-specific guidance is selected.

3. **Use docs as guidance, not rigid law**
   - Follow the most applicable guidance to the user request and current repo.
