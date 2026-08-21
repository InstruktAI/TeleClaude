---
description: Incorporate, update, or remove third-party skill packages without rewriting their upstream content.
activation_trigger: Use when a needed skill is absent from the curated global index, or when an indexed skill must be made always-on inside one project.
---

# Skill Management — Procedure

## Goal

Bring a third-party skill under TeleClaude curation — globally, project-locally, or
both — preserving its upstream package, and keep updates and removals explicit.

## Preconditions

- `general/procedure/skill-use` was consulted and no curated skill matches the need, or
  a curated skill must additionally be made always-on inside a project.
- The human has approved the upstream source.
- The work runs from a durable main checkout: the TeleClaude repository for global
  adoption, the target project for project-local work.

## Steps

Two destinations exist and they are independent. A package may reach either or both.
Read step 4 before reaching for a project destination.

1. **Fetch to a scratch location and read it.** Download the approved upstream package
   into a temporary directory and read its `SKILL.md`. Report what the skill does and
   what it would change about how you work, then ask whether to use it now. Nothing is
   adopted at this step — a skill read from scratch is already usable for the rest of the
   session without being installed anywhere.

2. **Preserve upstream authorship.** Do not rewrite headings, restructure the body, add
   TeleClaude sections, or add `teleclaude_taxonomy`. Only `SKILL.md` frontmatter is
   normalized: `name` and `description` must be non-empty, and `name` must equal the
   containing folder. Scripts, references, and assets are copied verbatim and stay
   opaque to TeleClaude taxonomy validation.

3. **Adopt globally — the default destination.** Place the complete package at
   `agents/skills/<name>/` in the TeleClaude repository and commit it there. The package
   body is third-party content TeleClaude does not govern — it is never graded against
   TeleClaude's artifact taxonomy, and no todo carries it — while the commit itself
   routes through the normal agent-artifact review path like any other change under
   `agents/`. Sync publishes it to `~/.teleclaude/skills/<name>` as a digest-pinned
   `~/.teleclaude/skill-store/<digest>/<name>` snapshot, and
   `general/procedure/skill-use` lists it from there on. Every agent can then find it
   on demand without any project doing anything.

4. **Adopt project-locally — only for these two reasons.** Copy the complete package
   into the project's `.agents/skills/<name>/`:
   - the skill must fire without an agent first consulting the index, because a
     project-local skill is deployed into the agent runtime's own skill folder and is
     therefore preloaded; or
   - the skill must not be global — project-private, licence-bound, or too narrow to
     earn a line in the shared catalog.

   Absent one of those, step 3 is the destination. "Install" does not mean "install into
   a project"; an agent that reaches for `.agents/skills/` because a human said
   "install" has misread the request.

5. **Link an already-curated skill into a project.** When an indexed skill must be
   always-on in one project, resolve `~/.teleclaude/skills/<name>` to its exact
   `~/.teleclaude/skill-store/<digest>/<name>` target and symlink that immutable
   snapshot into `.agents/skills/<name>`. Never link through the floating catalog name —
   the symlink target is the installed-state record. The new link is not retroactively
   added to the current session's preloaded context; read the installed package directly
   for the remainder of the session.

6. **Update deliberately.** Compare the installed package against its current upstream
   or catalog snapshot and assess the behavioral impact from the actual diff. For a
   global package, replace the contents of `agents/skills/<name>/` and commit. For a
   project link, repoint it at the exact current snapshot. No semver, compatibility
   range, or machine-authored breaking-change classification participates in the
   decision.

7. **Remove cleanly.** Removing from a project means deleting that project's symlink or
   package directory. Removing globally means deleting `agents/skills/<name>/` in the
   TeleClaude repository and committing. Never delete a catalog entry or an immutable
   store snapshot through a project path.

8. **Validate and verify.** Run `telec sync`, then confirm the package reached its
   intended scope: a global adoption appears in the `general/procedure/skill-use`
   listing, a project adoption or link appears in that project's rendered runtime
   artifacts.

## Outputs

- An intact third-party package at global scope, project scope, or both.
- For catalog links, a project link pinned to one immutable digest snapshot.
- Rendered runtime artifacts refreshed by the watcher-owned publication pipeline.

## Recovery

- If a project link targets the floating catalog name, replace it with a direct link to
  the resolved immutable snapshot before continuing.
- If upstream content was rewritten or given TeleClaude taxonomy metadata, restore the
  upstream package and repeat incorporation without modification.
- If a package was adopted project-locally without one of step 4's two reasons, move it
  to `agents/skills/<name>/` and remove the project copy.
- If validation fails, leave the prior state in place, correct the reported source
  problem, and rerun the operation.
