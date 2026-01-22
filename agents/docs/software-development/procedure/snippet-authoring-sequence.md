---
description:
  Ten-step sequence for producing cohesive, atomic docs without losing
  context.
id: software-development/procedure/snippet-authoring-sequence
scope: domain
type: procedure
---

# Snippet Authoring Sequence (10 Steps)

1. **Define intent first** — pick one taxonomy type and a single responsibility.
2. **Find the smallest complete unit** — it must stand alone without hidden dependencies.
3. **Preserve cohesion** — keep coupled rules and constraints together.
4. **Split only on true separability** — split only when parts are independently usable.
5. **Choose domain-first placement** — mirror the repo’s business model in folder structure.
6. **Write frontmatter** — `id`, `type`, `scope`, `description`, `requires` (if needed).
7. **Use type-specific structure** — procedures are steps, policies are rules, references are structured lookups.
8. **Minimize the body** — include only what is required to act correctly.
9. **Validate against reality** — ensure alignment with code, process, and system behavior.
10. **Rebuild and validate** — run docs sync (`telec init` or `scripts/build_snippet_index.py`), which regenerates indexes automatically.
