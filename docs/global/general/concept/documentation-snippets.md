---
description: 'Modular documentation system for selective context delivery to AI agents.'
id: 'general/concept/documentation-snippets'
scope: 'global'
type: 'concept'
---

# Documentation Snippets — Concept

## What

Documentation snippets are atomic markdown files that each capture one idea — a concept,
policy, procedure, design decision, or spec. Each snippet declares its type
and scope in frontmatter, follows a schema specific to that type, and can declare hard
dependencies on other snippets.

Snippets exist in two scopes:

- **Global** — cross-project knowledge (coding standards, procedures, shared policies),
  maintained in the TeleClaude repo and distributed to `~/.teleclaude/docs/` for all
  projects.
- **Project** — knowledge specific to one repository, living alongside its code.

Agents retrieve snippets on demand via `teleclaude__get_context` rather than loading
everything upfront.

## Why

AI agents work within limited context windows. Bundling all documentation into every
prompt wastes tokens and dilutes signal. Snippets make knowledge modular and selectively
retrievable — an agent pulls only what it needs for the task at hand. The global/project
split keeps shared knowledge maintained once and project-specific knowledge local, without
duplication.
