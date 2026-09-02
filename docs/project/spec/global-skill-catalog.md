---
description: Private catalog composition, immutable digest storage, and project inclusion semantics for reusable skills.
---

# Global Skill Catalog — Spec

## What it is

The global skill catalog is TeleClaude's private, human-curated discovery surface for
reusable skill packages shared across registered projects. It is not a public package
registry and does not make TeleClaude a publisher of upstream skill content.

<!-- planned-change:agent-artifact-source-layout -->
Any registered project contributes a package by placing a direct named folder at
`agents/skills/<name>/`; folder existence is the publication declaration. The Mother
project alone owns `general/procedure/skill-use` and therefore the catalog's agent
instructions. A contributed package remains authored by its upstream source and passes
through TeleClaude's rendering pipeline without acquiring TeleClaude's heading taxonomy.
<!-- change:agent-artifact-source-layout -->
The mother repository contributes every package by placing a direct named folder at
`agents/global/skills/<name>/`; folder existence is the publication declaration. A side
project that authors a portable skill contributes it to the mother, which is the
curation step; a global skill folder in a side project is refused at validation. The
Mother project alone owns `general/procedure/skill-use` and therefore the catalog's
agent instructions. A contributed package remains authored by its upstream source and
passes through TeleClaude's rendering pipeline without acquiring TeleClaude's heading
taxonomy.
<!-- /planned-change:agent-artifact-source-layout -->

## Canonical fields

### Source, snapshot, and pointers

- **Atomic entry:** each catalog name is one self-contained capability. An entry never
  requires another entry to function, and never references an upstream package outside
  the catalog. Where upstream splits a capability across an invoker and a body, or across
  several composed packages, `general/procedure/skill-management` resolves the split
  before the package enters the catalog.
<!-- planned-change:agent-artifact-source-layout -->
- **Canonical source:** the publisher's Git-owned `agents/skills/<name>/` folder.
<!-- change:agent-artifact-source-layout -->
- **Canonical source:** the mother's Git-owned `agents/global/skills/<name>/` folder.
<!-- /planned-change:agent-artifact-source-layout -->
- **Immutable runtime snapshot:**
  `~/.teleclaude/skill-store/<content-digest>/<name>/`. Sync computes the package-tree
  digest and materializes the source once at that address. The store is runtime state,
  not an alternate authoring location.
- **Floating catalog name:** `~/.teleclaude/skills/<name>` is a symlink to the current
  immutable snapshot for that name. A later publisher refinement and successful sync
  move this pointer to the new digest.
<!-- planned-change:agent-artifact-source-layout -->
- **Installed project state:** `.agents/skills/<name>` links directly to one immutable
  snapshot. It never links through the floating catalog pointer. The symlink target is
  the complete lock: name plus exact content digest. No semver or compatibility range is
  maintained.
<!-- change:agent-artifact-source-layout -->
- **Installed project state:** the project declares the pin under its own authored
  source, `agents/project/skills/<name>`, linked directly to one immutable snapshot. It
  never links through the floating catalog pointer. The symlink target is the complete
  lock: name plus exact content digest. No semver or compatibility range is maintained.
  The delivered `.agents/skills/<name>` is output written from that declaration, never
  the declaration itself.
<!-- /planned-change:agent-artifact-source-layout -->

The duplicated snapshot bytes are what allow a project to remain on its selected content
after the publisher source and floating catalog name advance. Registered Git sources stay
canonical; the store exists only to retain immutable runtime materializations shared by
all projects pinned to the same digest.

### Sync composition

<!-- planned-change:agent-artifact-source-layout -->
1. Sync discovers direct named skill folders from the current project, Mother project,
   and all registered publisher roots.
2. Duplicate names from different publishers hard-block composition.
<!-- change:agent-artifact-source-layout -->
1. Sync discovers direct named skill folders from the mother's `agents/global/skills/`.
2. A global skill folder in any other registered root is a validation finding naming the
   folder, and it blocks the sync.
<!-- /planned-change:agent-artifact-source-layout -->
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

The catalog deploys to `~/.teleclaude/skills/`, never into an agent runtime's native
skills folder, so no agent loads a global skill without asking for it. The global agent
baseline carries a curated index entry for `general/procedure/skill-use`, which renders
the listing on demand; a package absent from that listing is incorporated through
`general/procedure/skill-management`.

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
