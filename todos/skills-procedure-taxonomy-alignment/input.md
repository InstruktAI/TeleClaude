# Input: skills-procedure-taxonomy-alignment

## Context

Roadmap entry:

- Extract procedure logic from `agents/skills` into docs procedures.
- Align skill wrappers with breath-aware taxonomy.
- Current scope is exploratory and limited to skills (no command/agent/runtime changes).

## Why this matters

- Current skill artifacts embed long procedures directly in each `SKILL.md`.
- Workflow logic is harder to reuse and maintain when policy/procedure content lives only in wrappers.
- A taxonomy-aligned wrapper model should improve consistency and reduce drift between docs and skill prompts.

## Initial assumptions

1. This todo does not change daemon behavior, transport behavior, or service lifecycle.
2. This todo does not add third-party dependencies.
3. Exploratory lane likely includes skills oriented to discovery, sensing, or diagnosis.
4. Skill wrappers must remain valid against artifact schema and distribution tooling.

## Known unknowns

1. Canonical list of skills included in the exploratory lane for this pass.
2. Canonical destination path and naming pattern for extracted procedure docs.
3. Whether new taxonomy docs must be added to baseline manifests in this same todo.
