# Context Weighting Rules

Injected snippet context may include overlapping guidance. When guidance conflicts:

1. **Prefer more specific scope over less specific**
   - Project > Domain > Global

2. **Prefer framework-specific scaffolding over generic scaffolding**
   - Use generic scaffolding only when no framework-specific guidance is selected.

3. **Use snippets as guidance, not rigid law**
   - Follow the most applicable guidance to the user request and current repo.
