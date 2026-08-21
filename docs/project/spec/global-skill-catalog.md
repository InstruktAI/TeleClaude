---
description: Private catalog composition, immutable digest storage, and project inclusion semantics for reusable skills.
---

# Global Skill Catalog — Spec

## What it is

The global skill catalog is TeleClaude's private, human-curated discovery surface for
reusable skill packages shared across registered projects. It is not a public package
registry and does not make TeleClaude a publisher of upstream skill content.

Any registered project contributes a package by placing a direct named folder at
`agents/skills/<name>/`; folder existence is the publication declaration. The Mother
project alone owns `agents/skills/AGENTS.master.md` and therefore the catalog's agent
instructions. A contributed package remains authored by its upstream source and passes
through TeleClaude's rendering pipeline without acquiring TeleClaude's heading taxonomy.

## Canonical fields

### Source, snapshot, and pointers

- **Canonical source:** the publisher's Git-owned `agents/skills/<name>/` folder.
- **Immutable runtime snapshot:**
  `~/.teleclaude/skill-store/<content-digest>/<name>/`. Sync computes the package-tree
  digest and materializes the source once at that address. The store is runtime state,
  not an alternate authoring location.
- **Floating catalog name:** `~/.teleclaude/skills/<name>` is a symlink to the current
  immutable snapshot for that name. A later publisher refinement and successful sync
  move this pointer to the new digest.
- **Installed project state:** `.agents/skills/<name>` links directly to one immutable
  snapshot. It never links through the floating catalog pointer. The symlink target is
  the complete lock: name plus exact content digest. No semver or compatibility range is
  maintained.

The duplicated snapshot bytes are what allow a project to remain on its selected content
after the publisher source and floating catalog name advance. Registered Git sources stay
canonical; the store exists only to retain immutable runtime materializations shared by
all projects pinned to the same digest.

### Sync composition

1. Sync discovers direct named skill folders from the current project, Mother project,
   and all registered publisher roots.
2. Duplicate names from different publishers hard-block composition.
<!-- planned-change:drop-skill-taxonomy-optin -->
3. Each entrypoint receives universal identity validation: non-empty `name` and
   `description`, with `name` equal to the containing folder. Body taxonomy runs only
   when `SKILL.md` declares `teleclaude_taxonomy: true`; supporting Markdown is opaque.
<!-- change:drop-skill-taxonomy-optin -->
3. Each entrypoint receives universal identity validation: non-empty `name` and
   `description`, with `name` equal to the containing folder. Skill bodies and supporting
   Markdown are opaque to taxonomy validation.
<!-- /planned-change:drop-skill-taxonomy-optin -->
4. Sync computes each package-tree digest and materializes any missing immutable
   snapshot under the skill store.
5. Sync assembles `.skills.next` from name-to-snapshot symlinks and atomically swaps it
   into `~/.teleclaude/skills`, retaining the previous catalog for rollback during the
   operation.
6. With the links already assembled, sync renders the Mother-owned catalog master through
   the normal artifact pipeline. The master is an orientation note for the catalog
   directory and carries no index of its own.
7. A rendering failure restores the previous catalog and leaves project-installed links
   untouched.

### Discovery

The catalog is not preloaded into any agent. `general/procedure/skill-use` is announced
as an activatable procedure and renders the index on demand; a package absent from that
listing is incorporated through `general/procedure/skill-management`.

### Authorship

<!-- planned-change:drop-skill-taxonomy-optin -->
The catalog is a third-party curation surface. Packages enter through
`general/procedure/skill-management`, keep their upstream structure, and do not opt into
TeleClaude taxonomy. Every package uses the same rendering pipeline.
<!-- change:drop-skill-taxonomy-optin -->
The catalog is a third-party curation surface. Packages enter through
`general/procedure/skill-management` and keep their upstream structure. Every package
uses the same rendering pipeline.
<!-- /planned-change:drop-skill-taxonomy-optin -->

## Known caveats

- The store currently retains snapshots indefinitely. Garbage collection must preserve
  every digest targeted by an installed project link; deleting by age alone would break
  pinned projects.
- A catalog name floats only after a successful sync. Publisher edits that have not
  passed validation and composition do not change the catalog pointer.
- Project-only packages copied directly from an external source do not use the global
  store and have no catalog-managed update path.
- The catalog's generated `AGENTS.md` is an orientation note for the catalog directory,
  not an index, package metadata, or an authorship claim over contributed content. The
  index is rendered on demand by `general/procedure/skill-use`.
