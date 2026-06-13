---
description: 'Modular documentation system for selective context delivery to AI agents.'
visibility: 'public'
---

# Documentation Snippets — Concept

## What

Documentation snippets are atomic markdown files that each capture one idea — a principle,
concept, policy, procedure, design, spec, or decision record (ADR). Each snippet declares its type
and scope in frontmatter, follows a schema specific to that type, and can declare hard
dependencies on other snippets.

Snippets exist in two scopes:

- **Global** — cross-project knowledge (coding standards, procedures, shared policies),
  maintained in the TeleClaude repo and distributed to `~/.teleclaude/docs/` for all
  projects.
- **Project** — knowledge specific to one repository, living alongside its code.

Agents retrieve snippets on demand via `telec docs index` + `telec docs get`
rather than loading
everything upfront.

Every type except `adr` is a **living, present-tense contract** — it states what is
currently true (the shape, the rule, the behavior) and is rewritten as reality changes.
`adr` is the sole exception: a **frozen, dated, append-only decision _record_** capturing
_why_ a contestable choice was made. A `design` snippet is the _shape_ (what); an `adr`
is the _reasoning behind a decision_ (why). **Design is not a record, and an ADR is not
design.**

## Why

AI agents work within limited context windows. Bundling all documentation into every
prompt wastes tokens and dilutes signal. Snippets make knowledge modular and selectively
retrievable — an agent pulls only what it needs for the task at hand. The global/project
split keeps shared knowledge maintained once and project-specific knowledge local, without
duplication.
