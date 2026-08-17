---
description: Author first-party taxonomy-governed skills as thin activation wrappers over canonical TeleClaude resources.
---

# Skill Authoring — Procedure

## Goal

Create a first-party thin-wrapper skill whose knowledge and behavior remain in
canonical TeleClaude resources rather than being duplicated into the wrapper.

## Preconditions

- A request to create or update a first-party skill.
- The artifact-scope policy and agent-artifacts spec are available.

## Steps

1. **Reject incorporation work.** A copied or linked package authored elsewhere is
   third-party skill management, not authoring. Follow
   `general/procedure/skill-management`; never rewrite that package into TeleClaude's
   taxonomy or claim its content as first-party authorship.
2. **Choose scope.** Apply the artifact-scope policy. A cross-project first-party
   skill lives under `agents/skills/<name>/` in its owning publisher. A project-only
   first-party skill lives under `.agents/skills/<name>/`.
3. **Gate the thin wrapper.** A first-party skill exists when an agent runtime needs
   a skill-shaped activation surface over canonical docs, a command corpus, or
   deterministic packaged tooling. If ordinary progressive disclosure of procedural
   knowledge is sufficient, create an activatable doc procedure instead and stop.
4. **Identify the knowledge source.** Locate or first author the doc snippets that
   carry the procedure or specification, or identify the canonical command/tooling
   surface the skill activates. The skill is an interface to that source, never its
   duplicate.
5. **Create the thin-wrapper directory** in the scope selected at step 2. Add
   `scripts/` only when the capability includes deterministic packaged tooling; keep
   those scripts standalone, executable, and self-documenting.
6. **Write the thin wrapper's `SKILL.md`.** Declare `name`, `description`, and
   `teleclaude_taxonomy: true`. Use one H1, optional `## Required reads` immediately
   after it, then `## Purpose`, `## Scope`, `## Inputs`, `## Outputs`, and
   `## Procedure`; optional `## See Also` comes last. Required reads point at the
   canonical sources, while Procedure only explains how to activate or invoke them.
7. **Keep package resources in their native formats.** Supporting Markdown is not
   taxonomy-validated; the authored entrypoint is taxonomy-governed while resources
   retain the structure suited to their purpose.


8. **Run `telec sync`** to validate, render, and deploy through the common artifact
   pipeline.
9. **Verify** the skill appears at the intended global or project runtime scope,
   retains its supporting resources, and triggers correctly.


## Outputs

- A first-party taxonomy-governed thin wrapper over canonical TeleClaude resources.


- A skill validated, rendered, and deployed via `telec sync`.


## Recovery

- If `telec sync` fails, fix the issue and rerun.
- If a wrapper duplicates procedural knowledge instead of activating its canonical
  source, move that knowledge into a doc snippet and keep only the activation surface.
- If the requested package is third-party, stop authoring and use the skill-management
  procedure without modifying its upstream structure.
