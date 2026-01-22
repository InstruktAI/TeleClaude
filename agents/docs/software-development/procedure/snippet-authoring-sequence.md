---
description:
  Ten-step sequence for producing cohesive, atomic docs without losing
  context.
id: software-development/procedure/snippet-authoring-sequence
scope: domain
type: procedure
---

# Snippet Authoring Sequence (10 Steps)

1. **Define intent first** — pick exactly one taxonomy type (see baseline taxonomy procedure).
2. **Find the smallest complete unit** — ensure it can stand alone without hidden context.
3. **Preserve cohesion** — keep tightly coupled information together.
4. **Split only on true separability** — split only if parts can be used independently.
5. **Choose domain-first placement** — mirror the repo’s business model in folder structure.
6. **Write frontmatter** — `id`, `type`, `scope`, `description`, `requires` (if needed).
7. **Use type-specific structure** — steps for procedures, rules for policies, tables for references, etc.
8. **Minimize the body** — include only what is necessary to use it correctly.
9. **Validate against source** — confirm it matches reality (code/process/system).
10. **Rebuild and validate** — `python ~/.teleclaude/scripts/build_snippet_index.py` then `python ~/.teleclaude/scripts/sync_docs.py`.
