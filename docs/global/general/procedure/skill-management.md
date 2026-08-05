---
description: Incorporate, update, or remove third-party skill packages without rewriting their upstream content.
activation_trigger: Use when a project needs to discover, incorporate, update, or remove a third-party skill.
---

# Skill Management — Procedure

## Goal

Incorporate a human-curated third-party skill into a project, preserve its upstream
package, and keep upgrades explicit.

## Preconditions

- The human has requested skill discovery, inclusion, update, or removal.
- The work runs from the project's durable main checkout.
- The package is third-party. First-party skill creation follows
  `general/procedure/skill-authoring` instead.

## Steps

1. **Choose the source.** Use the private global catalog for a skill already curated
   by a registered publisher. For a package needed only by this project and absent
   from the catalog, use the human-approved upstream source directly.
2. **Preserve upstream authorship.** Do not rewrite headings, add TeleClaude sections,
   or add `teleclaude_taxonomy`. The package's `SKILL.md` must retain non-empty `name`
   and `description`, with `name` equal to its folder; supporting resources remain
   opaque to TeleClaude taxonomy validation.

<!-- planned-change:command-migration-to-singular-telec-skill -->

3. **Refresh the catalog before discovery.** Run `telec sync`, then read
   `~/.teleclaude/skills/AGENTS.md` only because skill discovery or project inclusion
   is now requested.
4. **Install from the catalog.** Resolve `~/.teleclaude/skills/<name>` to its exact
   immutable `~/.teleclaude/skill-store/<digest>/<name>` snapshot. Create
   `.agents/skills/<name>` as a symlink directly to that snapshot, never to the
   floating catalog name. The symlink target is the installed-state record.
5. **Install a project-only upstream package.** Copy the complete package into
   `.agents/skills/<name>/`, including its scripts, references, and assets. This copy
   has no catalog update source; a later refresh repeats the human-reviewed import.
6. **Update deliberately.** Compare the installed package with the catalog's current
   snapshot. The calling agent assesses the behavioral impact from the actual diff.
   When an update is warranted, repoint the project symlink to the exact current
   snapshot. No semver, compatibility range, or machine-authored breaking-change
   classification participates in the decision.
7. **Remove cleanly.** Remove the project symlink or project-owned package directory;
   never delete the catalog entry or immutable store snapshot through the project path.
8. **Render and verify.** Run `telec sync`; confirm the project runtime receives the
   selected package through the normal artifact rendering pipeline.

<!-- change:command-migration-to-singular-telec-skill -->

3. **Discover curated packages.** Run `telec context skills list`. Auto-disclosed
   infrastructure skills are omitted by default because they require no project install;
   include them only when auditing the complete catalog.
4. **Install from the catalog.** Run `telec context skills install <name>`. The command
   resolves the catalog's current immutable snapshot, links the project directly to that
   exact snapshot, and runs sync. The project never links to the floating catalog name.
5. **Install a project-only upstream package.** Copy the complete human-approved
   package into `.agents/skills/<name>/`, including scripts, references, and assets,
   then run `telec sync`. This package has no catalog update source.
6. **Update deliberately.** Inspect the installed-to-current package diff and assess
   its behavioral impact. When the update is warranted, run
   `telec context skills update <name>`; it atomically repoints the project to the
   catalog's exact current snapshot and syncs. No semver, compatibility range, or
   machine-authored breaking-change classification participates in the decision.
7. **Remove cleanly.** Run `telec context skills remove <name>`. The command removes
   only the project link and syncs; it does not delete catalog or store content.

<!-- /planned-change:command-migration-to-singular-telec-skill -->

## Outputs

- An intact third-party package incorporated at project scope.
- For catalog installs, a project link pinned to one immutable digest snapshot.
- Rendered runtime artifacts refreshed by `telec sync`.

## Recovery

- If the project link targets the floating catalog name, replace it with a direct link
  to the resolved immutable snapshot before continuing.
- If upstream content was rewritten or given TeleClaude taxonomy metadata, restore the
  upstream package and repeat incorporation without modification.
- If sync fails, leave the prior project link in place, correct the reported source
  problem, and rerun the operation.
