---
id: 'project/adr/0011-grouped-snippets-folder-convention'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '11'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Related snippets that share a topic live in a folder named for the topic, with overview.md as the shared entry and sibling files for variants. The flat-prefix-sibling pattern (foo-overview.md / foo-human.md / foo-project.md) is rejected.'
---
# ADR-0011: Grouped Snippets Use overview.md Folder Convention — ADR

## Context

When the memory-extraction procedure was first authored, it landed as three flat sibling files in `docs/global/general/procedure/`: `memory-extraction.md`, `memory-extraction-human.md`, `memory-extraction-project.md`. This shared-prefix-sibling shape produced two problems:

- It diverged from an existing convention used throughout the codebase (e.g., `software-development/procedure/lifecycle/overview.md` + `lifecycle/integrate.md` + `lifecycle/prepare.md` + `lifecycle/work.md`).
- The shared prefix is purely lexical; the relationship between the three siblings (general procedure + variants) is implicit, not structural.

The convention used elsewhere is folder-based: the topic gets a folder; `overview.md` is the shared entry; siblings are named for their variant ("human", "project", "integrate", "prepare"). The relationship becomes structural — the folder IS the group.

This convention wasn't documented in the snippet authoring schema; agents authoring grouped snippets had no guidance and defaulted to the flat-prefix shape.

## Decision

Related snippets that share a topic live in a folder named for the topic. The folder contains:

- `overview.md` — the top-level or shared snippet for the group (e.g., the general procedure that variants build on, or the design overview of a family).
- Sibling files for specialized variants, named for what they cover (e.g., `human.md`, `project.md`, `prepare.md`, `work.md`).

The folder name becomes part of every member snippet's id (e.g., `general/procedure/memory-extraction/overview`, `general/procedure/memory-extraction/human`). Variants reference the overview as a required read. All members share the same taxonomy type — a folder under `procedure/` contains only `procedure` snippets.

The flat-prefix-sibling shape (e.g., `foo-overview.md` / `foo-human.md` / `foo-project.md`) is REJECTED. Existing snippets that landed in the flat shape are migrated to the folder shape when touched.

This convention is documented in `docs/global/general/spec/snippet-authoring-schema.md` under "Grouped snippets — folder convention."

## Consequences

**Positive:**

- The grouping relationship is structural (folder membership), not lexical (filename prefix). New variants land in the folder without filename gymnastics.
- IDs reflect the hierarchy. `general/procedure/memory-extraction/human` reads naturally; `general/procedure/memory-extraction-human` doesn't.
- Aligned with the existing convention used in `lifecycle/`, `sdlc/`, etc. Future agents see one pattern, not two.
- The convention is now in the schema doc, so future authoring follows it without re-derivation.

**Negative:**

- Existing snippets in the flat-prefix shape (if any besides the memory-extraction set) accumulate a small migration backlog. They should be migrated on touch.
- An overview.md isn't a strictly required file (a folder could have only sibling variants without a shared base); the convention says when an overview-equivalent makes sense, it's named `overview.md`. Folders without one are allowed but should be reviewed for whether an overview is missing.

## Alternatives Considered

- **Keep flat-prefix siblings.** Rejected: diverges from existing convention; makes the grouping relationship implicit.
- **Use a manifest file at the folder root.** Considered. Rejected as over-engineered: the folder IS the manifest. An `overview.md` plus discoverable siblings via the file system is enough.
- **Document the convention only in examples, not in the schema.** Rejected: agents authoring new grouped snippets need explicit guidance, not pattern recognition from existing snippets that they may or may not have seen.